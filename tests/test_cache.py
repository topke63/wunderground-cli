import time

import httpx

from wunderground_cli import api, cache, cli
from typer.testing import CliRunner


def _ok(data):
    return httpx.Response(200, json=data, request=httpx.Request("GET", "http://x"))


def test_second_call_served_from_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: calls.append(url) or _ok({"a": 1}))
    assert api._get("/p", {"x": 1}) == {"a": 1}
    assert api._get("/p", {"x": 1}) == {"a": 1}
    assert len(calls) == 1
    api._get("/p", {"x": 2})
    assert len(calls) == 2


def test_expired_entry_refetched(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: calls.append(url) or _ok({"a": 1}))
    api._get("/p", {})
    monkeypatch.setattr(cache, "TTL_SECONDS", -1)
    api._get("/p", {})
    assert len(calls) == 2


def test_disabled_cache_never_stores(monkeypatch):
    monkeypatch.setattr(cache, "enabled", False)
    calls = []
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: calls.append(url) or _ok({"a": 1}))
    api._get("/p", {})
    api._get("/p", {})
    assert len(calls) == 2 and cache.clear() == 0


def test_corrupt_cache_file_ignored(monkeypatch):
    cache.put("/p", {}, {"a": 1})
    for f in cache.CACHE_DIR.glob("*.json"):
        f.write_text("garbage")
    assert cache.get("/p", {}) is None


def test_cache_clear_command():
    cache.put("/p", {}, {"a": 1})
    result = CliRunner().invoke(cli.app, ["cache-clear"])
    assert "Removed 1" in result.output and cache.get("/p", {}) is None
