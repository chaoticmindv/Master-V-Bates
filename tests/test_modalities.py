"""
Unit tests for multi-modality support (Text, Code/Webdev, Search, Image, Max Router).
"""

import json
import unittest
from unittest.mock import MagicMock

from arena.models import (
    MODALITIES, MAX_ROUTER_ID, get_models_for_modality, check_model_capability
)
from arena.api import ArenaClient


class TestModalities(unittest.TestCase):
    def setUp(self):
        self.mock_models = [
            {
                "id": MAX_ROUTER_ID,
                "name": "Max (Router)",
                "org": "boss-bandit",
                "arena": "text",
                "is_router": True,
                "user_selectable": True,
                "capabilities": {}
            },
            {
                "id": "model-webdev-1",
                "name": "Claude Sonnet 5 Webdev",
                "org": "anthropic",
                "arena": "code",
                "rank": 1,
                "user_selectable": True,
                "capabilities": {
                    "outputCapabilities": {"web": True, "text": True}
                }
            },
            {
                "id": "model-search-1",
                "name": "Grok 4.5 Search",
                "org": "xai",
                "arena": "search",
                "rank": 2,
                "user_selectable": True,
                "capabilities": {
                    "outputCapabilities": {"search": True, "text": True}
                }
            },
            {
                "id": "model-text-only",
                "name": "GPT-5 Standard",
                "org": "openai",
                "arena": "text",
                "rank": 5,
                "user_selectable": True,
                "capabilities": {
                    "outputCapabilities": {"text": True}
                }
            },
            {
                "id": "model-image-1",
                "name": "Flux Ultra",
                "org": "black-forest",
                "arena": "text-to-image",
                "rank": 1,
                "user_selectable": True,
                "capabilities": {
                    "outputCapabilities": {"image": True}
                }
            },
            {
                "id": "model-video-1",
                "name": "Veo Video",
                "org": "google",
                "arena": "text-to-video",
                "rank": 3,
                "user_selectable": True,
                "capabilities": {
                    "outputCapabilities": {"video": True}
                }
            }
        ]

    def test_modality_definitions(self):
        self.assertIn("chat", MODALITIES)
        self.assertIn("webdev", MODALITIES)
        self.assertIn("search", MODALITIES)
        self.assertIn("image", MODALITIES)
        self.assertIn("video", MODALITIES)

        self.assertEqual(MODALITIES["webdev"]["api_modality"], "webdev")
        self.assertEqual(MODALITIES["search"]["api_modality"], "search")
        self.assertEqual(MODALITIES["image"]["api_modality"], "image")
        self.assertEqual(MODALITIES["video"]["api_modality"], "video")
        self.assertEqual(MODALITIES["chat"]["api_modality"], "chat")

    def test_get_models_for_modality(self):
        # Search modality should include Max Router and search model
        search_models = get_models_for_modality(self.mock_models, "search")
        ids = [m["id"] for m in search_models]
        self.assertIn(MAX_ROUTER_ID, ids)
        self.assertIn("model-search-1", ids)
        self.assertNotIn("model-text-only", ids)

        # Webdev modality should include Max Router and webdev model
        web_models = get_models_for_modality(self.mock_models, "webdev")
        web_ids = [m["id"] for m in web_models]
        self.assertIn(MAX_ROUTER_ID, web_ids)
        self.assertIn("model-webdev-1", web_ids)
        self.assertNotIn("model-image-1", web_ids)

        # Video must use the video arena/capabilities, never the image list
        video_models = get_models_for_modality(self.mock_models, "video")
        video_ids = [m["id"] for m in video_models]
        self.assertIn("model-video-1", video_ids)
        self.assertNotIn("model-image-1", video_ids)

    def test_check_model_capability(self):
        router = self.mock_models[0]
        web_model = self.mock_models[1]
        search_model = self.mock_models[2]
        text_model = self.mock_models[3]

        # Router can handle all modalities
        self.assertTrue(check_model_capability(router, "search"))
        self.assertTrue(check_model_capability(router, "webdev"))
        self.assertTrue(check_model_capability(router, "image"))
        self.assertTrue(check_model_capability(router, "chat"))

        # Dedicated models
        self.assertTrue(check_model_capability(web_model, "webdev"))
        self.assertTrue(check_model_capability(search_model, "search"))
        self.assertTrue(check_model_capability(self.mock_models[5], "video"))
        self.assertFalse(check_model_capability(self.mock_models[4], "video"))

        # Text-only model cannot handle search
        self.assertFalse(check_model_capability(text_model, "search"))

    def test_stream_parser_detects_deployment_and_sources(self):
        client = ArenaClient("dummy_cookie")
        
        # Mock SSE stream containing text, a preview deployment URL, and search source
        mock_chunks = [
            b'a0:"Starting the app build..."\n',
            b'a2:{"sandboxUrl":"https://sandbox-preview.arena-preview.ai/app-123"}\n',
            b'ah:{"title":"Python Docs","url":"https://docs.python.org"}\n',
            b'a0:"\nBuild complete!"\n'
        ]
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = mock_chunks

        events = list(client.parse_stream(mock_resp))
        types = [e[0] for e in events]
        
        self.assertIn("text", types)
        self.assertIn("preview_url", types)
        self.assertIn("source", types)

        # Check preview URL extracted
        preview_event = next(e for e in events if e[0] == "preview_url")
        self.assertEqual(preview_event[1], "https://sandbox-preview.arena-preview.ai/app-123")
        self.assertEqual(client.last_preview_url, "https://sandbox-preview.arena-preview.ai/app-123")

        # Check source extracted
        source_event = next(e for e in events if e[0] == "source")
        self.assertEqual(source_event[1]["url"], "https://docs.python.org")
        self.assertEqual(len(client.sources), 1)


if __name__ == "__main__":
    unittest.main()

