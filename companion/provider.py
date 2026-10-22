"""Minimal configurable Chat Completions transport. Does not execute model actions."""
from dataclasses import dataclass
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIConfig:
    base_url: str = 'https://api.openai.com/v1'
    model: str = ''
    key: str = ''
    vision_model: str = ''
    timeout: float = 60

    @classmethod
    def from_env(cls):
        return cls(base_url=os.getenv('A11Y_AI_BASE_URL', cls.base_url).rstrip('/'),
                   model=os.getenv('A11Y_AI_MODEL', ''),
                   key=os.getenv('A11Y_AI_KEY', os.getenv('OPENAI_API_KEY', '')),
                   vision_model=os.getenv('A11Y_VISION_MODEL', ''))

    def validate(self):
        if not self.model:
            raise ProviderError('AI is not configured. Set A11Y_AI_MODEL and A11Y_AI_KEY '
                                '(or a local compatible endpoint) before requesting AI help.')
        parsed = urlparse(self.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ProviderError('Invalid AI endpoint URL.')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ProviderError('AI endpoints must use HTTPS, except local loopback endpoints.')
        if parsed.hostname == 'api.openai.com' and not self.key:
            raise ProviderError('Set A11Y_AI_KEY or OPENAI_API_KEY to enable the configured provider.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward company context or authorization to an unexpected endpoint.
        raise ProviderError('AI endpoint redirects are disabled. Configure its final URL.')


class ChatProvider:
    def __init__(self, config=None):
        self.config = config or AIConfig.from_env()

    def complete_structured(self, system, messages, *, schema, image_data=None, max_tokens=3000, thinking=None):
        return self.complete(system+'\nReturn only JSON matching this schema:\n'+json.dumps(schema),
                             messages, image_data=image_data, max_tokens=max_tokens)

    def complete(self, system, messages, *, image_data=None, max_tokens=None):
        self.config.validate()
        messages = [dict(m) for m in messages]
        if image_data:
            messages[-1]['content'] = [
                {'type': 'text', 'text': messages[-1]['content']},
                {'type': 'image_url', 'image_url': {'url': image_data}}]
        body = {'model': (self.config.vision_model or self.config.model) if image_data else self.config.model,
                'messages': [{'role': 'system', 'content': system}] + messages,
                'response_format': {'type': 'json_object'}, 'stream': False}
        if max_tokens is not None:
            body['max_tokens'] = max_tokens
        headers = {'Content-Type': 'application/json'}
        if self.config.key:
            headers['Authorization'] = f'Bearer {self.config.key}'
        req = urllib.request.Request(self.config.base_url.rstrip('/') + '/chat/completions',
                                     json.dumps(body).encode(), headers)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=self.config.timeout) as response:
                payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise ProviderError('AI response exceeded the size limit.')
            envelope = json.loads(payload)
            choice = envelope['choices'][0]
            if choice.get('finish_reason') not in (None, 'stop'):
                raise ProviderError('AI response was incomplete or refused. Please try a narrower request.')
            content = choice['message']['content']
            if not isinstance(content, str):
                raise ProviderError('AI returned no text response.')
            return json.loads(content)
        except urllib.error.HTTPError as e:
            # Provider bodies may echo private input: never display them or store request payloads.
            raise ProviderError(f'AI provider returned HTTP {e.code}. Check model, credentials, and quota.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderError('Could not reach the AI provider. Check the endpoint and connection.') from None
        except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError):
            raise ProviderError('AI provider returned an invalid JSON response. No actions were applied.') from None
