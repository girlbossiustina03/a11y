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


class OllamaProvider:
    def __init__(self, config=None):
        self.config = config or AIConfig(
            base_url=os.getenv('A11Y_OLLAMA_URL', 'http://127.0.0.1:11434'),
            model=os.getenv('A11Y_AI_MODEL', ''), vision_model=os.getenv('A11Y_VISION_MODEL', ''), timeout=120)
        self.metadata = {}

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
            code = e.code
            e.close()
            raise ProviderError(f'Ollama returned HTTP {code}. Ensure the selected model is installed with ollama list.') from None
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

    def complete(self, system, messages, *, image_data=None):
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
        result = self.request('/api/chat', {
            'model': model, 'messages': [{'role': 'system', 'content': system}] + messages,
            'stream': False, 'format': RESPONSE_SCHEMA, 'keep_alive': '5m',
            'options': {'temperature': 0.3, 'num_ctx': 8192, 'num_predict': 3000}})
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
