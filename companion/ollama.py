"""Native local Ollama transport. No API key, cloud fallback, downloads or tool execution."""
import json
import os
from urllib.parse import urlparse
import urllib.error
import urllib.request
from .models import RESPONSE_SCHEMA
from .provider import AIConfig, ChatProvider, NoRedirect, ProviderError


def local_url(value):
    parsed = urlparse(value)
    if (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ProviderError('Ollama must use a local loopback address, for example http://127.0.0.1:11434.')
    return value.rstrip('/')


class OllamaRequestError(ProviderError):
    def __init__(self, code, category):
        self.code, self.category = code, category
        guidance = {
            'schema': 'Ollama rejected the structured-output schema.',
            'vision': 'Ollama rejected the image request. Check the selected vision model.',
            'thinking': 'Ollama rejected the thinking option. Use A11Y_OLLAMA_THINKING=default.',
            'context': 'Ollama rejected the context size. Check A11Y_OLLAMA_CONTEXT.',
            'memory': 'Ollama could not load the model into available memory.',
            'missing': 'Ollama could not find the requested model or endpoint. Check the AI connection and ollama list.',
            'request': 'Ollama rejected the request; this does not establish that the model is missing.'}
        super().__init__(guidance[category]+f' (HTTP {code})')


def error_category(code, payload):
    """Classify bounded local errors without showing echoed prompts, images or secrets."""
    try:
        error = json.loads(payload).get('error', '')
        if isinstance(error, dict):
            error = error.get('message', '')
        detail = error.casefold() if isinstance(error, str) else ''
    except (ValueError, AttributeError, TypeError):
        detail = ''
    if 'grammar' in detail or 'json schema' in detail or 'json_schema' in detail or 'schema' in detail and 'format' in detail:
        return 'schema'
    if 'image' in detail or 'vision' in detail:
        return 'vision'
    if 'thinking' in detail or 'think' in detail:
        return 'thinking'
    if 'context' in detail or 'num_ctx' in detail:
        return 'context'
    if any(word in detail for word in ('memory', 'allocation', 'out of vram')):
        return 'memory'
    return 'missing' if code == 404 else 'request'


def grammar_schema(schema):
    """Large string-length grammar expansions can fail; executors enforce bounds."""
    if isinstance(schema, list):
        return [grammar_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {key: grammar_schema(value) for key, value in schema.items()
            if not (key == 'maxLength' and isinstance(value, int) and value > 256)}


class OllamaProvider:
    def __init__(self, config=None):
        self.config = config or AIConfig(
            base_url=os.getenv('A11Y_OLLAMA_URL', 'http://127.0.0.1:11434'),
            model=os.getenv('A11Y_AI_MODEL', ''), vision_model=os.getenv('A11Y_VISION_MODEL', ''), timeout=120)
        self.metadata = {}
        self.json_fallbacks = set()

    def request(self, path, body=None, *, timeout=None):
        endpoint = local_url(self.config.base_url)
        req = urllib.request.Request(endpoint+path,
            None if body is None else json.dumps(body).encode(), {'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
                    req, timeout=timeout or self.config.timeout) as response:
                payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise ProviderError('Ollama response exceeded the size limit.')
            result = json.loads(payload)
            if not isinstance(result, dict) or result.get('error'):
                raise ProviderError('Ollama could not complete the request. Check the selected local model.')
            return result
        except urllib.error.HTTPError as e:
            try:
                try:
                    payload = e.read(8192)
                except (OSError, ValueError):
                    payload = b''
                category = error_category(e.code, payload)
            finally:
                e.close()
            raise OllamaRequestError(e.code, category) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise ProviderError('Local Ollama is not reachable. Run ollama serve in a separate terminal, '
                                'then select Find local Ollama models in AI connection.') from None
        except (ValueError, TypeError):
            raise ProviderError('Ollama returned an invalid response. No actions were applied.') from None

    def model_info(self, name):
        if name not in self.metadata:
            result = self.request('/api/show', {'model': name}, timeout=5)
            if result.get('remote_host') or result.get('remote_model') or name.endswith((':cloud', '-cloud')):
                raise ProviderError('Choose a model downloaded locally. Cloud-backed Ollama models are disabled.')
            self.metadata[name] = result
        return self.metadata[name]

    def list_models(self):
        result = self.request('/api/tags', timeout=3)
        items = result.get('models')
        if not isinstance(items, list):
            raise ProviderError('Ollama returned an invalid model list.')
        models = []
        for item in items[:50]:
            if not isinstance(item, dict):
                continue
            name = item.get('name', '')
            if (not isinstance(name, str) or not name or item.get('remote_host') or item.get('remote_model')
                    or name.endswith((':cloud', '-cloud'))):
                continue
            info = self.model_info(name)
            capabilities = info.get('capabilities', [])
            if 'completion' in capabilities:
                models.append({'name': name, 'vision': 'vision' in capabilities})
        return models

    def interpret_request(self, request, recent_users=()):
        from .request_plan import INTENT_SCHEMA, INTENT_SYSTEM, validate_plan
        payload = {'recent_user_requests': list(recent_users)[-2:], 'current_request': request}
        return validate_plan(self.complete(INTENT_SYSTEM, [{'role': 'user', 'content': json.dumps(payload)}],
                                          response_schema=INTENT_SCHEMA, max_tokens=400, thinking=False))

    def complete_structured(self, system, messages, *, schema, image_data=None):
        return self.complete(system, messages, image_data=image_data, response_schema=schema)

    def complete(self, system, messages, *, image_data=None, response_schema=None, max_tokens=3000, thinking=None):
        local_url(self.config.base_url)
        if not self.config.model:
            raise ProviderError('Select a local model in Settings → AI connection → Find local Ollama models.')
        model = (self.config.vision_model or self.config.model) if image_data else self.config.model
        info = self.model_info(model)
        if image_data and 'vision' not in info.get('capabilities', []):
            raise ProviderError('The selected local model cannot read images. Choose an installed vision model '
                                'in AI connection. Text chat and task planning remain available.')
        messages = [dict(m) for m in messages]
        if image_data:
            messages[-1]['images'] = [image_data.split(',', 1)[1]]
        try:
            context_length = int(os.getenv('A11Y_OLLAMA_CONTEXT', '16384'))
            if not 4096 <= context_length <= 65536:
                raise ValueError()
        except ValueError:
            raise ProviderError('A11Y_OLLAMA_CONTEXT must be an integer from 4096 to 65536.') from None
        schema = response_schema if response_schema is not None else RESPONSE_SCHEMA
        wire_schema = grammar_schema(schema)
        schema_key = (model, json.dumps(wire_schema, sort_keys=True))
        body = {'model': model, 'messages': [{'role': 'system', 'content': system}] + messages,
            'stream': False, 'format': wire_schema, 'keep_alive': '5m',
            'options': {'temperature': 0.2, 'num_ctx': context_length, 'num_predict': max_tokens}}
        requested_thinking = thinking
        thinking = os.getenv('A11Y_OLLAMA_THINKING', 'default').lower()
        if thinking not in ('default', 'true', 'false'):
            raise ProviderError('A11Y_OLLAMA_THINKING must be default, true or false.')
        if thinking != 'default':
            body['think'] = thinking == 'true'
        if requested_thinking is not None and ('thinking' in info.get('capabilities', []) or requested_thinking in info.get('thinking', {}).get('values', [])):
            body['think'] = requested_thinking
        def json_mode():
            body['format'] = 'json'
            body['messages'][0] = {'role': 'system', 'content': system+'\nReturn ONLY a JSON object matching this schema. All action bounds are validated locally:\n'+json.dumps(schema)}
        if schema_key in self.json_fallbacks:
            json_mode()
        try:
            result = self.request('/api/chat', body)
        except OllamaRequestError as error:
            if error.code != 400 or error.category != 'schema' or body['format'] == 'json':
                raise
            # Only an inference request was rejected; no desktop action was sent.
            json_mode()
            result = self.request('/api/chat', body)
            self.json_fallbacks.add(schema_key)
        try:
            if result.get('done') is not True or result.get('done_reason') not in (None, 'stop'):
                raise ProviderError('Ollama response was incomplete. Try a shorter request.')
            content = result['message']['content']
            return json.loads(content)
        except (KeyError, TypeError, ValueError):
            raise ProviderError('The local model did not return valid JSON. No actions were applied.') from None


def provider_from_env():
    kind = os.getenv('A11Y_AI_PROVIDER', '').lower()
    if kind not in ('', 'ollama', 'compatible'):
        raise ProviderError('A11Y_AI_PROVIDER must be ollama or compatible.')
    if kind == 'compatible' or (not kind and (os.getenv('A11Y_AI_BASE_URL') or os.getenv('A11Y_AI_KEY') or os.getenv('OPENAI_API_KEY'))):
        return ChatProvider()
    return OllamaProvider()
