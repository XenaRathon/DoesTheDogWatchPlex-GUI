import pytest
import requests
import responses
import logging
from unittest.mock import patch

from dtdd import DTDDClient, DTDD_BASE

@responses.activate
def test_dtdd_client_retries(caplog):
    caplog.set_level(logging.WARNING)
    client = DTDDClient(api_key="test", retries=3, api_delay=0)

    url = f"{DTDD_BASE}/dddsearch?q=test"

    # 1st call: 429 Too Many Requests
    responses.add(responses.GET, url, status=429)
    # 2nd call: 503 Service Unavailable
    responses.add(responses.GET, url, status=503)
    # 3rd call: 200 OK
    responses.add(responses.GET, url, status=200, json={"items": [{"id": 123}]})

    with patch("time.sleep"):  # to speed up backoff
        res = client.search("test")

    assert len(res) == 1
    assert res[0]["id"] == 123
    assert len(responses.calls) == 3

    # Verify it logged retries
    assert any("Retrying" in record.message for record in caplog.records)

@responses.activate
def test_dtdd_client_no_retry_404(caplog):
    client = DTDDClient(api_key="test", retries=3, api_delay=0)

    url = f"{DTDD_BASE}/dddsearch?q=test_404"

    # 404 should not be retried
    responses.add(responses.GET, url, status=404)

    with pytest.raises(requests.exceptions.HTTPError):
        client.search("test_404")

    assert len(responses.calls) == 1

def test_dtdd_client_fallback_log(caplog):
    caplog.set_level(logging.INFO)
    client = DTDDClient(api_key="test", retries=None)
    assert any("falling back to default" in record.message.lower() for record in caplog.records)
