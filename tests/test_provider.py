import unittest
from companion.provider import AIConfig, NoRedirect, ProviderError


class ProviderTests(unittest.TestCase):
    def config(self, **kwargs):
        return AIConfig(model='configured-model', key='test-key', **kwargs)

    def test_https_required_except_loopback(self):
        for url in ['http://remote.example/v1', 'file:///tmp/provider', 'https://user:password@example.com',
                    'https://example.com/v1?key=secret']:
            with self.assertRaises(ProviderError):
                self.config(base_url=url).validate()
        self.config(base_url='http://127.0.0.1:11434/v1').validate()

    def test_redirects_cannot_forward_sensitive_context(self):
        with self.assertRaises(ProviderError):
            NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://other-host/')
