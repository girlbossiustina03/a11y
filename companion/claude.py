"""Claude (Anthropic API) transport: an opt-in alternative to the local Ollama model.

With Claude selected, requests, recent conversation, app and window names and the company
documents a question uses are sent to Anthropic; screen images only after the user allows
screen vision for Claude. Mail, Calendar, Reminders, Notes and Contacts are still read on
this computer and shown directly. The model only proposes; every action goes through the
same local validation, access checks and confirmations as with Ollama."""
import json
import os
import sys
import threading
import time
from .models import RESPONSE_SCHEMA
from .ollama import Planner, RequestCancelled
from .provider import AIConfig, ProviderError
from .timing import timing

MODEL = 'claude-sonnet-5-5'
ENDPOINT = 'https://api.anthropic.com'
KEY_FILE = 'anthropic-key'
WORKSPACE_FILE = 'anthropic-workspace'  # needed by user keys (sk-ant-usr-…) that have no workspace
# Refusals in some categories are retried on another Claude model inside the same call.
FALLBACK_BETA = 'server-side-fallback-2026-07-01'
# Structured outputs accept a subset of JSON Schema; bounds are enforced locally anyway
# (models.validate_response, request_plan.validate_plan, computer_task checks).
UNSUPPORTED = {'minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
               'multipleOf', 'maxItems', 'uniqueItems', 'pattern'}
EFFORTS = ('low', 'medium', 'high')


def key_path():
    from .paths import data_dir
    return data_dir()/KEY_FILE


def saved_key():
    """ANTHROPIC_API_KEY wins; otherwise the key saved in Settings."""
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if key:
        return key
    try:
        return key_path().read_text().strip()[:300]
    except OSError:
        return ''


def saved_workspace():
    workspace = os.getenv('ANTHROPIC_WORKSPACE_ID', '').strip()
    if workspace:
        return workspace
    try:
        from .paths import data_dir
        return (data_dir()/WORKSPACE_FILE).read_text().strip()[:120]
    except OSError:
        return ''


def save_workspace(workspace):
    from .paths import data_dir
    path = data_dir()/WORKSPACE_FILE
    if not workspace:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(workspace.strip())


WORKSPACE_HELP = ('This Anthropic key is a user key without a workspace. Create an API key in console.anthropic.com → '
                  'API keys (it starts with sk-ant-api) and paste it in Settings → Advanced → AI model, or add your '
                  'workspace ID there.')


def save_key(key):
    """Keep the key in A11y's per-user data folder, readable only by this user. Empty forgets it."""
    path = key_path()
    if not key:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(key.strip())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def wire_schema(node):
    """The schema as Claude's structured outputs accept it: no numeric/length bounds and every
    object closed. Arrays always name their items."""
    if isinstance(node, list):
        return [wire_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {key: wire_schema(value) for key, value in node.items()
              if key not in UNSUPPORTED and not (key == 'minItems' and value not in (0, 1))}
    if result.get('type') == 'object' or 'properties' in result:
        result['additionalProperties'] = False
    if result.get('type') == 'array' and 'items' not in result:
        result['items'] = {'type': 'string'}
    return result


def wrapped(schema):
    """Structured outputs need an object at the top; other roots (the task step's anyOf) are
    carried in a single 'result' property and unwrapped after decoding."""
    if schema.get('type') == 'object':
        return schema, False
    return {'type': 'object', 'additionalProperties': False, 'required': ['result'],
            'properties': {'result': schema}}, True


def image_block(image_data):
    header, _, data = image_data.partition(',')
    media = header[5:].split(';')[0] if header.startswith('data:') else ''
    if media not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp') or not data:
        raise ProviderError('The screen image could not be prepared for Claude. Nothing was sent.')
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': media, 'data': data}}


def claude_messages(messages, image_data=None):
    """App messages as Claude expects them: user first, user last, no empty text."""
    result = []
    for message in messages:
        role, content = message.get('role'), message.get('content')
        if not isinstance(content, str) or not content.strip():
            continue
        role = role if role in ('user', 'assistant') else 'user'
        if not result and role == 'assistant':
            continue
        result.append({'role': role, 'content': content})
    if not result or result[-1]['role'] != 'user':
        result.append({'role': 'user', 'content': 'Continue with the request above.'})
    if image_data:
        last = result[-1]
        result[-1] = {'role': 'user', 'content': [image_block(image_data), {'type': 'text', 'text': last['content']}]}
    return result


class ClaudeProvider(Planner):
    cloud = True  # screen images need their own consent (see vision.capture)

    def __init__(self, config=None, *, key=None, workspace=None):
        self.config = config or AIConfig(base_url=ENDPOINT, model=os.getenv('A11Y_CLAUDE_MODEL', MODEL),
                                         key=key if key is not None else saved_key(), timeout=90)
        self.workspace = workspace if workspace is not None else saved_workspace()
        self.json_fallbacks = set()
        self.use_fallback = True  # turned off for the session if the API rejects it
        self._client = None
        self._client_lock = threading.Lock()

    def ready_error(self):
        if not self.config.key:
            return 'Add your Anthropic API key in Settings → Advanced → AI model to use Claude.'
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return 'This build has no Claude support. Install the anthropic package or use the local model.'
        return ''

    def client(self):
        with self._client_lock:
            if self._client is None:
                error = self.ready_error()
                if error:
                    raise ProviderError(error)
                import anthropic
                headers = {'anthropic-workspace-id': self.workspace} if self.workspace else None
                self._client = anthropic.Anthropic(api_key=self.config.key, base_url=self.config.base_url,
                                                   timeout=self.config.timeout, max_retries=2, default_headers=headers)
            return self._client

    def model_info(self, name):
        return {'capabilities': ['completion', 'vision']}

    def list_models(self):
        return [{'name': self.config.model, 'vision': True}]

    def warm_up(self, systems):
        pass  # Anthropic caches the instructions on the first real request

    def complete_structured(self, system, messages, *, schema, image_data=None, max_tokens=3000, thinking=None, cancel=None):
        return self.complete(system, messages, image_data=image_data, response_schema=schema,
                             max_tokens=max_tokens, thinking=thinking, cancel=cancel)

    def effort(self, image_data):
        # Looking at the screen to pick a click target is where extra thought pays off;
        # routing and chat stay quick.
        chosen = os.getenv('A11Y_CLAUDE_EFFORT', '').lower()
        return chosen if chosen in EFFORTS else ('medium' if image_data else 'low')

    def complete(self, system, messages, *, image_data=None, response_schema=None, max_tokens=3000, thinking=None, cancel=None):
        schema, unwrap = wrapped(response_schema if response_schema is not None else RESPONSE_SCHEMA)
        wire = wire_schema(schema)
        schema_key = json.dumps(wire, sort_keys=True)
        import anthropic
        while True:
            request = {'model': self.config.model, 'max_tokens': 16000,  # thinking shares this limit
                       'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                       'messages': claude_messages(messages, image_data),
                       'output_config': {'effort': self.effort(image_data),
                                         'format': {'type': 'json_schema', 'schema': wire}}}
            if self.use_fallback:
                request.update(betas=[FALLBACK_BETA], fallbacks='default')
            if schema_key in self.json_fallbacks:
                self.json_mode(request, system, wire)
            try:
                message = self.send(request, image_data, cancel)
                break
            except anthropic.BadRequestError as error:
                detail = error_detail(error)
                print('A11y Claude request rejected:', detail, '| request id:', getattr(error, 'request_id', ''), file=sys.stderr, flush=True)
                if 'anthropic-workspace-id' in detail:
                    raise ProviderError(WORKSPACE_HELP) from None  # the request is fine; the key needs a workspace
                # Optional parts go one at a time, and the session remembers: first the refusal
                # fallback (a beta), then the strict schema (the same JSON asked for in words).
                if self.use_fallback:
                    self.use_fallback = False
                elif schema_key not in self.json_fallbacks:
                    self.json_fallbacks.add(schema_key)
                else:
                    raise ProviderError('Claude rejected the request (HTTP 400: '+detail+'). Nothing was done.') from None
        result = self.parse(message)
        if unwrap:
            if not isinstance(result, dict) or 'result' not in result:
                raise ProviderError('Claude did not return valid JSON. No actions were applied.')
            return result['result']
        return result

    @staticmethod
    def json_mode(request, system, wire):
        del request['output_config']['format']
        request['system'] = [{'type': 'text', 'cache_control': {'type': 'ephemeral'},
                              'text': system+'\nReturn ONLY a JSON object matching this schema, with no other text:\n'+json.dumps(wire)}]

    def send(self, request, image_data, cancel):
        """Stream one request. Stop returns at once: a blocked read cannot be woken from another
        thread, so the request runs on a worker that drops the late answer and closes the
        connection at its next event."""
        if cancel is None:
            return self.stream(request, image_data, None)
        if cancel.is_set():
            raise RequestCancelled()
        outcome, done = {}, threading.Event()

        def run():
            try:
                outcome['message'] = self.stream(request, image_data, cancel)
            except BaseException as error:  # handed to the waiting caller
                outcome['error'] = error
            finally:
                done.set()
        threading.Thread(target=run, daemon=True).start()
        while not done.wait(0.05):
            if cancel.is_set():
                raise RequestCancelled()
        if 'error' in outcome:
            raise outcome['error']
        return outcome['message']

    def stream(self, request, image_data, cancel):
        import anthropic
        started = time.monotonic()
        timing('claude.start', started, image=bool(image_data), effort=request['output_config']['effort'])
        try:
            messages_api = self.client().beta.messages if 'betas' in request else self.client().messages
            with messages_api.stream(**request) as stream:
                for _ in stream:
                    if cancel is not None and cancel.is_set():
                        raise RequestCancelled()
                message = stream.get_final_message()
        except RequestCancelled:
            timing('claude.cancelled', started)
            raise
        except anthropic.AuthenticationError:
            raise ProviderError('Claude did not accept the API key. Check it in Settings → Advanced → AI model.') from None
        except anthropic.PermissionDeniedError:
            raise ProviderError('This API key is not allowed to use '+self.config.model+'.') from None
        except anthropic.NotFoundError:
            raise ProviderError('Claude could not find the model '+self.config.model+'.') from None
        except anthropic.RateLimitError:
            raise ProviderError('Claude is rate limited right now. Wait a moment and try again.') from None
        except anthropic.BadRequestError:
            raise
        except anthropic.APIStatusError as error:
            # Provider bodies may echo private input: show only the status.
            raise ProviderError(f'Claude is unavailable right now (HTTP {error.status_code}). Try again shortly.') from None
        except (anthropic.APIConnectionError, anthropic.APITimeoutError):
            raise ProviderError('Could not reach Claude. Check the internet connection.') from None
        usage = getattr(message, 'usage', None)
        # Never log prompts, screenshots or model text; token counts only.
        timing('claude.finished', started, stop=message.stop_reason,
               input_tokens=getattr(usage, 'input_tokens', None), output_tokens=getattr(usage, 'output_tokens', None),
               cache_read=getattr(usage, 'cache_read_input_tokens', None))
        return message

    @staticmethod
    def parse(message):
        if message.stop_reason == 'refusal':
            raise ProviderError('Claude declined this request. Nothing was done.')
        if message.stop_reason == 'max_tokens':
            raise ProviderError('I got lost in a long answer and stopped. Nothing was done; please ask again, a bit more specifically.')
        text = ''.join(block.text for block in message.content if getattr(block, 'type', '') == 'text').strip()
        if text.startswith('```'):
            text = text.strip('`').removeprefix('json').strip()
        try:
            return json.loads(text)
        except ValueError:
            raise ProviderError('Claude did not return valid JSON. No actions were applied.') from None


def error_detail(error):
    """Anthropic's own reason for a rejected request (it names the field at fault), shortened."""
    body = getattr(error, 'body', None)
    detail = body.get('error', {}).get('message', '') if isinstance(body, dict) and isinstance(body.get('error'), dict) else ''
    detail = ' '.join(str(detail or getattr(error, 'message', '') or 'no reason given').split())
    return detail[:220]
