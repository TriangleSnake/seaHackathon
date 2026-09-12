from __future__ import annotations

import base64
import copy
import hashlib
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx


IndicatorType = Literal["url", "domain"]
_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_ANALYSIS_CATEGORIES = ("harmless", "malicious", "suspicious", "undetected", "timeout")


class VirusTotalError(RuntimeError):
    """Safe, credential-free VirusTotal integration error."""


def normalize_indicator(indicator_type: IndicatorType, indicator: str) -> str:
    value = indicator.strip()
    if not value or len(value) > 2048:
        raise ValueError("indicator must contain between 1 and 2048 characters")

    if indicator_type == "url":
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url indicator must be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("url indicator must not contain embedded credentials")
        # Fragments are client-side only and are not part of the fetched resource.
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, "")
        )

    candidate = value.lower().rstrip(".")
    if "://" in candidate or any(char in candidate for char in "/?#@:"):
        raise ValueError("domain indicator must contain only a hostname")
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("domain indicator is not a valid hostname") from exc
    labels = candidate.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValueError("domain indicator is not a valid hostname")
    return candidate


def url_identifier(url: str) -> str:
    """Return VirusTotal's supported unpadded base64 URL identifier."""
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def _evidence_id(indicator_type: IndicatorType, indicator: str) -> str:
    digest = hashlib.sha256(f"{indicator_type}:{indicator}".encode()).hexdigest()[:24]
    return f"VT-{indicator_type.upper()}-{digest}"


def _string_map(value: Any, limit: int = 30) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key)[:100]: str(item)[:300]
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:limit]
    }


def _bounded_text(value: Any, limit: int) -> str | None:
    return str(value)[:limit] if value is not None else None


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


class VirusTotalClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://www.virustotal.com/api/v3",
        timeout_seconds: float = 10,
        cache_ttl_seconds: float = 900,
        max_cache_entries: int = 256,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._cache_ttl_seconds = max(0, cache_ttl_seconds)
        self._max_cache_entries = max(1, max_cache_entries)
        self._cache: OrderedDict[
            tuple[str, str], tuple[float, dict[str, Any]]
        ] = OrderedDict()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_reputation(
        self, indicator_type: IndicatorType, indicator: str
    ) -> dict[str, Any]:
        if not self._api_key:
            raise VirusTotalError("VIRUSTOTAL_API_KEY is not configured")
        normalized = normalize_indicator(indicator_type, indicator)
        cache_key = (indicator_type, normalized)
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] > time.monotonic():
            self._cache.move_to_end(cache_key)
            return copy.deepcopy(cached[1])
        if cached is not None:
            del self._cache[cache_key]
        object_id = (
            url_identifier(normalized) if indicator_type == "url" else normalized
        )
        collection = "urls" if indicator_type == "url" else "domains"
        evidence_id = _evidence_id(indicator_type, normalized)

        try:
            response = await self._client.get(
                f"{self._base_url}/{collection}/{object_id}",
                headers={"accept": "application/json", "x-apikey": self._api_key},
            )
        except httpx.TimeoutException as exc:
            raise VirusTotalError("VirusTotal request timed out") from exc
        except httpx.HTTPError as exc:
            raise VirusTotalError("VirusTotal request failed") from exc

        common: dict[str, Any] = {
            "provider": "virustotal",
            "indicator": {"type": indicator_type, "value": normalized},
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "submitted_for_analysis": False,
        }
        if response.status_code == 404:
            result = {
                **common,
                "found": False,
                "message": "No existing VirusTotal report was found; this is not a harmless verdict.",
            }
            self._cache[cache_key] = (
                time.monotonic() + self._cache_ttl_seconds,
                result,
            )
            self._trim_cache()
            return copy.deepcopy(result)
        if response.status_code in {401, 403}:
            raise VirusTotalError("VirusTotal authentication or authorization failed")
        if response.status_code == 429:
            raise VirusTotalError("VirusTotal rate limit exceeded")
        if response.status_code >= 400:
            raise VirusTotalError(
                f"VirusTotal request failed with status {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise VirusTotalError("VirusTotal returned invalid JSON") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("attributes"), dict):
            raise VirusTotalError("VirusTotal returned an invalid report")

        attributes = data["attributes"]
        raw_stats = attributes.get("last_analysis_stats", {})
        stats = {
            category: int(raw_stats.get(category, 0))
            for category in _ANALYSIS_CATEGORIES
            if isinstance(raw_stats, dict)
            and isinstance(raw_stats.get(category, 0), (int, float))
        }
        tags = attributes.get("tags", [])
        raw_votes = attributes.get("total_votes", {})
        total_votes = {
            category: int(raw_votes.get(category, 0))
            for category in ("harmless", "malicious")
            if isinstance(raw_votes, dict)
            and isinstance(raw_votes.get(category, 0), (int, float))
        }
        report: dict[str, Any] = {
            "object_id": _bounded_text(data.get("id", object_id), 512),
            "type": _bounded_text(data.get("type", indicator_type), 50),
            "last_analysis_stats": stats,
            "last_analysis_date": _integer(attributes.get("last_analysis_date")),
            "reputation": _integer(attributes.get("reputation")),
            "total_votes": total_votes,
            "categories": _string_map(attributes.get("categories")),
            "tags": [str(tag)[:100] for tag in tags[:30]] if isinstance(tags, list) else [],
        }
        if indicator_type == "url":
            report.update(
                title=_bounded_text(attributes.get("title"), 500),
                final_url=_bounded_text(attributes.get("last_final_url"), 2048),
                targeted_brand=_string_map(attributes.get("targeted_brand"), 20),
            )

        result = {**common, "id": evidence_id, "found": True, "report": report}
        self._cache[cache_key] = (
            time.monotonic() + self._cache_ttl_seconds,
            result,
        )
        self._trim_cache()
        return copy.deepcopy(result)

    def _trim_cache(self) -> None:
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
