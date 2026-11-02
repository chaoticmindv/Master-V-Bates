"""Model catalog cache refresh tests."""

import json
import time

from arena import models


class CatalogResponse:
    def __init__(self, catalog):
        self._catalog = catalog

    def raise_for_status(self):
        pass

    def json(self):
        return self._catalog


def test_fresh_cache_skips_the_network(monkeypatch, tmp_path):
    cache = tmp_path / "models_cache.json"
    monkeypatch.setattr(models, "CACHE_FILE", cache)
    cached = [{"id": "cached", "name": "Cached", "arena": "text", "user_selectable": True}]
    cache.write_text(json.dumps({"_cached_at": time.time(), "models": cached}), encoding="utf-8")

    def fail(*args, **kwargs):
        raise AssertionError("the network must not be called for a fresh cache")

    monkeypatch.setattr(models.requests, "get", fail)
    assert models.sync_models(force=False) == cached


def test_expired_cache_refreshes_and_drops_removed_models(monkeypatch, tmp_path):
    cache = tmp_path / "models_cache.json"
    monkeypatch.setattr(models, "CACHE_FILE", cache)
    cache.write_text(json.dumps({
        "_cached_at": time.time() - models.CACHE_TTL_SECONDS - 1,
        "models": [{"id": "removed", "name": "Removed", "arena": "text", "user_selectable": True}],
    }), encoding="utf-8")
    catalog = [{"arena": "text", "models": [{
        "id": "new-model", "displayName": "New Model", "organization": "google",
        "userSelectable": True, "capabilities": {},
    }]}]
    monkeypatch.setattr(models.requests, "get", lambda *a, **k: CatalogResponse(catalog))

    result = models.sync_models(force=False)
    ids = [m["id"] for m in result]
    assert ids == ["new-model"]
    assert models.CACHE_TTL_SECONDS <= 600
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert [m["id"] for m in saved["models"]] == ["new-model"]
    assert saved["_cached_at"] > time.time() - 10
