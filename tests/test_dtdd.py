import json
import logging
import os
import pytest
from dtdd import DTDDClient, _make_safe_key, CACHE_DIR
import dtdd

def test_make_safe_key():
    # Regular titles
    assert _make_safe_key("search", "test") == "search_test_098f6bcd"

    # Titles with slashes, question marks, colons, unicode
    assert _make_safe_key("media", "123?index1=1&index2=2").startswith("media_123_index1_1_index2_2_")
    assert _make_safe_key("search", "title/with/slashes").startswith("search_title_with_slashes_")
    assert _make_safe_key("search", "title: with colons").startswith("search_title__with_colons_")
    assert _make_safe_key("search", "unicode ★ title").startswith("search_unicode___title_")

    # Very long titles
    long_title = "a" * 100
    safe_key = _make_safe_key("search", long_title)
    assert len(safe_key) == len("search") + 1 + 50 + 1 + 8 # prefix + _ + 50_chars_slug + _ + 8_chars_hash

def test_get_cache_corrupt_fallback(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(dtdd, "CACHE_DIR", tmp_path)
    client = DTDDClient("dummy_api_key")

    # Create an unreadable file
    unreadable_file = tmp_path / "test_unreadable.json"
    unreadable_file.write_text("corrupt data")

    # Create a corrupt JSON file
    corrupt_file = tmp_path / "test_corrupt.json"
    corrupt_file.write_text("{invalid_json: true")

    with caplog.at_level(logging.WARNING):
        # Should return None for unreadable/corrupt files and not crash
        assert client._get_cache("test_unreadable") is None
        assert client._get_cache("test_corrupt") is None

        # Check that warnings were logged
        assert "Failed to read cache for test_unreadable" in caplog.text
        assert "Failed to read cache for test_corrupt" in caplog.text

def test_dtdd_requests_timeout(requests_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(dtdd, "CACHE_DIR", tmp_path)
    client = DTDDClient("dummy_api_key")

    requests_mock.get(f"{dtdd.DTDD_BASE}/dddsearch", json={"items": []})
    client.search("test")
    assert requests_mock.last_request.timeout == 30

    requests_mock.get(f"{dtdd.DTDD_BASE}/dddsearch", json={"items": []})
    client.search_by_imdb("tt1234567")
    assert requests_mock.last_request.timeout == 30

    requests_mock.get(f"{dtdd.DTDD_BASE}/media/123", json={})
    client.get_media(123)
    assert requests_mock.last_request.timeout == 30
