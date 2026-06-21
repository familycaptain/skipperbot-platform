"""Registry resolves the openai connector on a COLD call via idempotent/lazy
self-registration — no explicit boot registration required (architecture review)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from providers import registry  # noqa: E402
from providers.base import ChatProvider, EmbeddingProvider  # noqa: E402
from providers.openai_provider import OpenAIProvider  # noqa: E402


class TestRegistryLazySelfRegistration(unittest.TestCase):
    def setUp(self):
        # simulate a cold process: clear the registries
        registry._chat_providers.clear()
        registry._embedding_providers.clear()

    def test_get_chat_provider_cold(self):
        prov = registry.get_chat_provider()          # no register_builtin_providers() called first
        self.assertIsInstance(prov, OpenAIProvider)
        self.assertIsInstance(prov, ChatProvider)

    def test_get_embedding_provider_cold(self):
        prov = registry.get_embedding_provider()
        self.assertIsInstance(prov, OpenAIProvider)
        self.assertIsInstance(prov, EmbeddingProvider)

    def test_register_builtin_is_idempotent(self):
        registry.register_builtin_providers()
        first = registry.get_chat_provider()
        registry.register_builtin_providers()        # second call must not replace/error
        self.assertIs(registry.get_chat_provider(), first)


if __name__ == "__main__":
    unittest.main()
