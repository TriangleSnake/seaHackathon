from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from app.client import VirusTotalClient, VirusTotalError, normalize_indicator, url_identifier


def test_url_identifier_uses_unpadded_urlsafe_base64() -> None:
    url = "https://example.test/path?q=1"
    expected = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    assert url_identifier(url) == expected
    assert "=" not in url_identifier(url)


def test_indicator_validation_and_normalization() -> None:
    assert normalize_indicator("domain", "Example.COM.") == "example.com"
    assert normalize_indicator("url", "HTTPS://example.com/a#fragment") == "https://example.com/a"
    with pytest.raises(ValueError, match="embedded credentials"):
        normalize_indicator("url", "https://user:secret@example.com/")
    with pytest.raises(ValueError, match="hostname"):
        normalize_indicator("domain", "https://example.com/path")


def test_existing_report_is_reduced_to_bounded_evidence() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert request.headers["x-apikey"] == "test-key"
        assert request.url.path.startswith("/api/v3/urls/")
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "url-object-id",
                    "type": "url",
                    "attributes": {
                        "last_analysis_stats": {
                            "harmless": 70,
                            "malicious": 2,
                            "suspicious": 1,
                            "undetected": 4,
                        },
                        "last_analysis_date": 123,
                        "reputation": -5,
                        "total_votes": {"harmless": 1, "malicious": 2},
                        "categories": {"vendor": "phishing"},
                        "tags": ["phishing"],
                        "title": "Example",
                    },
                }
            },
        )

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = VirusTotalClient("test-key", client=raw_client)
    result = asyncio.run(client.get_reputation("url", "https://example.test/path"))
    cached = asyncio.run(client.get_reputation("url", "https://example.test/path"))
    asyncio.run(raw_client.aclose())
    assert result["found"] is True
    assert result["submitted_for_analysis"] is False
    assert result["report"]["object_id"] == "url-object-id"
    assert result["report"]["last_analysis_stats"]["malicious"] == 2
    assert result["id"].startswith("VT-URL-")
    assert cached == result
    assert call_count == 1


def test_cache_has_a_bounded_lru_size() -> None:
    raw_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": {
                        "id": request.url.path.rsplit("/", 1)[-1],
                        "type": "domain",
                        "attributes": {"last_analysis_stats": {}},
                    }
                },
            )
        )
    )
    client = VirusTotalClient("test-key", max_cache_entries=2, client=raw_client)
    for domain in ("one.example", "two.example", "three.example"):
        asyncio.run(client.get_reputation("domain", domain))
    asyncio.run(raw_client.aclose())
    assert len(client._cache) == 2
    assert ("domain", "one.example") not in client._cache


def test_not_found_is_unknown_and_does_not_submit() -> None:
    raw_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, json={}))
    )
    client = VirusTotalClient("test-key", client=raw_client)
    result = asyncio.run(client.get_reputation("domain", "unknown.example"))
    asyncio.run(raw_client.aclose())
    assert result["found"] is False
    assert "id" not in result
    assert result["submitted_for_analysis"] is False
    assert "not a harmless verdict" in result["message"]


def test_missing_api_key_fails_only_when_tool_is_called() -> None:
    client = VirusTotalClient("")
    with pytest.raises(VirusTotalError, match="not configured"):
        asyncio.run(client.get_reputation("domain", "example.com"))
    asyncio.run(client.close())


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "authentication"), (403, "authorization"), (429, "rate limit")],
)
def test_provider_errors_are_sanitized(status: int, message: str) -> None:
    raw_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json={}))
    )
    client = VirusTotalClient("secret-key", client=raw_client)
    with pytest.raises(VirusTotalError, match=message):
        asyncio.run(client.get_reputation("domain", "example.com"))
    asyncio.run(raw_client.aclose())
