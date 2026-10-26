"""Shared model configuration, errors and redirect protection."""
from dataclasses import dataclass
import urllib.request
from urllib.parse import urlparse


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIConfig:
    base_url: str = 'http://127.0.0.1:11434'
    model: str = ''
    key: str = ''
    vision_model: str = ''
    timeout: float = 60

    def validate(self):
        if not self.model:
            raise ProviderError('Choose an installed local model before requesting AI help.')
        parsed = urlparse(self.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ProviderError('Invalid AI endpoint URL.')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ProviderError('AI endpoints must use HTTPS, except local loopback endpoints.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward private context or authorization to an unexpected endpoint.
        raise ProviderError('AI endpoint redirects are disabled. Configure its final URL.')
