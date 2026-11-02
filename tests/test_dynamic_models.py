"""
Unit tests for dynamic models catalog, caching, color mapping, and multi-browser MCP tools.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from arena.models import (
    get_org_color, sync_models, get_popular_models, CACHE_TTL_SECONDS
)
from arena.tools.browser_mcp import (
    BrowserDetectTool, BrowserOpenUrlTool
)


class TestDynamicModels(unittest.TestCase):
    def test_dynamic_org_colors(self):
        # Known labs have designated colors
        self.assertEqual(get_org_color("openai"), "#10B981")
        self.assertEqual(get_org_color("anthropic"), "#F97316")
        self.assertEqual(get_org_color("xai"), "#D946EF")

        # Unknown / newly introduced organizations get deterministic dynamic palette colors
        color_new1 = get_org_color("futuristic_ai_lab")
        color_new2 = get_org_color("futuristic_ai_lab")
        color_diff = get_org_color("another_new_org")

        self.assertTrue(color_new1.startswith("#"))
        self.assertEqual(color_new1, color_new2)  # Deterministic hash
        self.assertEqual(len(color_new1), 7)

    # keep the fake catalog out of the user's real ~/.arena-cli/models_cache.json
    @patch("arena.models.CACHE_FILE", Path(tempfile.gettempdir()) / "arena-test-models-cache.json")
    @patch("requests.get")
    def test_sync_models_caching(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "arena": "text",
                "models": [
                    {
                        "id": "model-1",
                        "displayName": "GPT-5.5 Instant",
                        "organization": "openai",
                        "rank": 43,
                        "userSelectable": True
                    },
                    {
                        "id": "model-2",
                        "displayName": "Claude 5 Sonnet",
                        "organization": "anthropic",
                        "rank": 58,
                        "userSelectable": True
                    }
                ]
            },
            {
                "arena": "code",
                "models": [
                    {
                        "id": "model-3",
                        "displayName": "DeepSeek Coder v3",
                        "organization": "deepseek",
                        "rank": 10,
                        "userSelectable": True
                    }
                ]
            }
        ]
        mock_get.return_value = mock_response

        # Force sync
        models = sync_models(cookie="test_cookie", force=True)
        self.assertEqual(len(models), 3)

        # Check fields normalized
        m1 = models[0]
        self.assertEqual(m1["id"], "model-1")
        self.assertEqual(m1["name"], "GPT-5.5 Instant")
        self.assertEqual(m1["org"], "openai")
        self.assertEqual(m1["rank"], 43)

        # Popular sorting sorts by rank
        popular = get_popular_models(models)
        self.assertEqual(len(popular), 3)
        self.assertEqual(popular[0]["id"], "model-3")  # Rank 10 comes first
        self.assertEqual(popular[1]["id"], "model-1")  # Rank 43 comes second
        self.assertEqual(popular[2]["id"], "model-2")  # Rank 58 comes third


class TestBrowserTools(unittest.TestCase):
    def test_browser_detect_tool(self):
        tool = BrowserDetectTool(cwd=os.getcwd())
        output = tool.execute({})
        self.assertIn("Installed & Available Browsers:", output)
        # Should detect at least Brave / Chrome / Edge on this Windows machine
        self.assertTrue("Brave" in output or "Edge" in output or "Chrome" in output)

    def test_browser_open_url_tool_validation(self):
        tool = BrowserOpenUrlTool(cwd=os.getcwd())
        err = tool.execute({"url": ""})
        self.assertIn("Error: No URL provided", err)


if __name__ == "__main__":
    unittest.main()
