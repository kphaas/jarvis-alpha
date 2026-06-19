"""Free/source-owned routes that can satisfy Beacon search requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Awaitable, Callable

from brain.services import weather_client as default_weather_client
from brain.services.internet_scout.evidence import (
    build_evidence_packet,
    build_source_reference,
)
from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutRequest,
)

WeatherClient = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

OPEN_METEO_SOURCE_URL = "https://" + "open-meteo.com/"

_WEATHER_SIGNAL_RE = re.compile(
    r"\b(?:weather|temperature|temp|conditions?|outside|rain(?:ing)?|"
    r"humidity|wind(?:y)?)\b",
    flags=re.IGNORECASE,
)
_WEB_SEARCH_DISQUALIFIER_RE = re.compile(
    r"\b(?:api|docs?|documentation|pricing|compare|comparison|versus|vs\.?|"
    r"news|article|historical|history|record|records?|source|site:)\b",
    flags=re.IGNORECASE,
)
_FORECAST_DISQUALIFIER_RE = re.compile(
    r"\b(?:forecast|tomorrow|weekend|next\s+week|next\s+month|tonight|later)\b",
    flags=re.IGNORECASE,
)
_EXPLICIT_NON_HOME_LOCATION_RE = re.compile(
    r"\b(?:in|near|around|for)\s+"
    r"(?!(?:today|now|right\s+now|home|the\s+house|here|near\s+me|"
    r"my\s+area|this\s+area|local|outside)\b)"
    r"[a-z][a-z0-9 .,'-]{2,}",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class FreeSourceRouteResult:
    """Evidence produced without consuming a paid search provider quota."""

    source_name: str
    provider: str
    packet: InternetEvidencePacket
    paid_search_avoided: bool = True


class FreeSourceRouter:
    """Route narrow current-fact questions to governed free adapters first."""

    def __init__(self, weather_client: WeatherClient | None = None) -> None:
        self.weather_client = (
            weather_client or default_weather_client.get_current_weather
        )

    async def try_route(
        self, request: InternetScoutRequest
    ) -> FreeSourceRouteResult | None:
        """Return evidence for a free source, or None when paid search is needed."""
        if _is_current_local_weather_query(request.query):
            weather_payload = await self.weather_client({"location_label": "home"})
            return FreeSourceRouteResult(
                source_name="weather.current",
                provider="open-meteo",
                packet=_packet_from_weather_payload(
                    request=request,
                    payload=weather_payload,
                ),
            )
        return None


def _is_current_local_weather_query(query: str | None) -> bool:
    if not query:
        return False
    normalized = _collapse_whitespace(query.lower())
    if not _WEATHER_SIGNAL_RE.search(normalized):
        return False
    if _WEB_SEARCH_DISQUALIFIER_RE.search(normalized):
        return False
    if _FORECAST_DISQUALIFIER_RE.search(normalized):
        return False
    return not _EXPLICIT_NON_HOME_LOCATION_RE.search(normalized)


def _packet_from_weather_payload(
    *,
    request: InternetScoutRequest,
    payload: dict[str, Any],
) -> InternetEvidencePacket:
    observed_at = _text_or_none(payload.get("observed_at"))
    fetched_at = _parse_observed_at(observed_at)
    citation_text = _weather_citation(payload)
    source_content = "\n".join(
        [
            "source=weather.current",
            "provider=open-meteo",
            f"location_label={_text_or_none(payload.get('location_label')) or 'home'}",
            f"observed_at={observed_at or 'unknown'}",
            f"condition={_text_or_none(payload.get('condition')) or 'unknown'}",
            f"temperature_f={payload.get('temperature_f')}",
            f"apparent_temperature_f={payload.get('apparent_temperature_f')}",
            f"relative_humidity_pct={payload.get('relative_humidity_pct')}",
            f"precipitation_in={payload.get('precipitation_in')}",
            f"wind_speed_mph={payload.get('wind_speed_mph')}",
            f"cached={payload.get('cached')}",
        ]
    )
    source = build_source_reference(
        url=OPEN_METEO_SOURCE_URL,
        content=source_content,
        title="Open-Meteo current weather via Alpha Gateway",
        fetched_at=fetched_at,
    )
    claim = EvidenceClaim(
        claim=citation_text,
        source_url=source.url,
        citation_text=citation_text,
        confidence="high",
    )
    return build_evidence_packet(request=request, sources=[source], claims=[claim])


def _weather_citation(payload: dict[str, Any]) -> str:
    location_label = _text_or_none(payload.get("location_label")) or "home"
    condition = _text_or_none(payload.get("condition")) or "unknown conditions"
    observed_at = _text_or_none(payload.get("observed_at"))
    parts = [
        f"Open-Meteo current weather for {location_label}: {condition}",
    ]
    temperature = _number(payload.get("temperature_f"))
    if temperature is not None:
        parts.append(f"{temperature:.0f}F")
    apparent = _number(payload.get("apparent_temperature_f"))
    if apparent is not None:
        parts.append(f"feels like {apparent:.0f}F")
    humidity = _number(payload.get("relative_humidity_pct"))
    if humidity is not None:
        parts.append(f"humidity {humidity:.0f}%")
    precipitation = _number(payload.get("precipitation_in"))
    if precipitation is not None:
        parts.append(f"precipitation {precipitation:.2f} in")
    wind_speed = _number(payload.get("wind_speed_mph"))
    if wind_speed is not None:
        parts.append(f"wind {wind_speed:.0f} mph")
    if observed_at:
        parts.append(f"observed {observed_at}")
    if payload.get("cached") is True:
        parts.append("Gateway cache hit")
    return "; ".join(parts) + "."


def _parse_observed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
