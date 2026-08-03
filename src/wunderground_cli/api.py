"""Client for the weather API used by k-donn/plasmoid-wunderground.

The plasmoid does not call The Weather Company / Wunderground API directly;
it goes through a public Cloudflare Worker proxy (wps.mitchell-*.workers.dev)
that injects the real API key server-side. This client talks to the same
proxy, so no API key is required here either.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Literal

import httpx

Units = Literal["metric", "imperial", "hybrid"]

_HOST_SHARDS = ["aaa", "a91", "0a3", "75b", "fd6"]
_UNIT_QUERY = {"metric": "m", "imperial": "e", "hybrid": "h"}
_UNIT_SECTION = {"metric": "metric", "imperial": "imperial", "hybrid": "uk_hybrid"}

_AQ_SCALE_BY_COUNTRY = {
    "CN": "HJ6332012",
    "FR": "ATMO",
    "DE": "UBA",
    "GB": "DAQI",
    "IN": "NAQI",
    "MX": "IMECA",
    "ES": "CAQI",
}


class WundergroundAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _api_host() -> str:
    shard = random.choice(_HOST_SHARDS)
    return f"https://wps.mitchell-{shard}.workers.dev"


def _get(path: str, params: dict[str, Any]) -> Any:
    url = f"{_api_host()}{path}"
    try:
        resp = httpx.get(url, params=params, timeout=10.0)
    except httpx.HTTPError as exc:
        raise WundergroundAPIError(f"Network error contacting {url}: {exc}") from exc

    if resp.status_code != 200:
        raise WundergroundAPIError(
            f"Request to {path} failed: HTTP {resp.status_code}", resp.status_code
        )

    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise WundergroundAPIError(f"Could not parse response from {path}: {exc}")


def _aq_scale(country_code: str | None) -> str:
    return _AQ_SCALE_BY_COUNTRY.get((country_code or "").upper(), "EPA")


@dataclass
class Station:
    station_id: str
    address: str
    latitude: float
    longitude: float


def search_stations(query: str, language: str = "en-US") -> list[Station]:
    """Search nearby PWS stations by free text (city, address, station id...)."""
    res = _get(
        "/v3/location/search",
        {"query": query, "locationType": "pws", "language": language, "format": "json"},
    )
    loc = (res or {}).get("location") or {}
    ids = loc.get("pwsId") or []
    names = loc.get("neighborhood") or []
    lats = loc.get("latitude") or []
    lons = loc.get("longitude") or []
    return [
        Station(station_id=ids[i], address=names[i] if i < len(names) else "",
                latitude=lats[i] if i < len(lats) else 0.0,
                longitude=lons[i] if i < len(lons) else 0.0)
        for i in range(len(ids))
    ]


def search_geocode(latitude: float, longitude: float) -> list[Station]:
    """Search PWS stations near a lat/lon coordinate."""
    res = _get(
        "/v3/location/near",
        {"geocode": f"{latitude},{longitude}", "product": "pws", "format": "json"},
    )
    loc = (res or {}).get("location") or {}
    ids = loc.get("stationId") or []
    names = loc.get("stationName") or []
    lats = loc.get("latitude") or []
    lons = loc.get("longitude") or []
    return [
        Station(station_id=ids[i], address=names[i] if i < len(names) else "",
                latitude=lats[i] if i < len(lats) else 0.0,
                longitude=lons[i] if i < len(lons) else 0.0)
        for i in range(len(ids))
    ]


def get_current_observation(station_id: str, units: Units = "metric") -> dict[str, Any]:
    """Fetch the most recent observation for a PWS station."""
    res = _get(
        "/v2/pws/observations/current",
        {
            "stationId": station_id,
            "format": "json",
            "units": _UNIT_QUERY[units],
            "numericPrecision": "decimal",
        },
    )
    observations = (res or {}).get("observations") or []
    if not observations:
        raise WundergroundAPIError(f"No observation returned for station {station_id}")

    obs = observations[0]
    section = obs.get(_UNIT_SECTION[units]) or {}
    return {
        "stationID": obs.get("stationID"),
        "neighborhood": obs.get("neighborhood"),
        "obsTimeLocal": obs.get("obsTimeLocal"),
        "latitude": obs.get("lat"),
        "longitude": obs.get("lon"),
        "humidity": obs.get("humidity"),
        "uv": obs.get("uv"),
        "winddir": obs.get("winddir"),
        "solarRadiation": obs.get("solarRadiation"),
        "temp": section.get("temp"),
        "heatIndex": section.get("heatIndex"),
        "dewpt": section.get("dewpt"),
        "windChill": section.get("windChill"),
        "windSpeed": section.get("windSpeed"),
        "windGust": section.get("windGust"),
        "pressure": section.get("pressure"),
        "precipRate": section.get("precipRate"),
        "precipTotal": section.get("precipTotal"),
        "elevation": section.get("elev"),
    }


def get_extended_conditions(
    latitude: float, longitude: float, units: Units = "metric", language: str = "en-US"
) -> dict[str, Any]:
    """Fetch area-level conditions: icon/narrative, alerts, and air quality."""
    res = _get(
        "/v3/aggcommon/v3-wx-observations-current;v3alertsHeadlines;v3-wx-globalAirQuality",
        {
            "geocodes": f"{latitude},{longitude}",
            "language": language,
            "scale": _aq_scale(language.split("-")[-1] if language else None),
            "units": _UNIT_QUERY[units],
            "format": "json",
        },
    )
    combined = (res or [None])[0] or {}
    cond = combined.get("v3-wx-observations-current") or {}
    alerts_raw = (combined.get("v3alertsHeadlines") or {}).get("alerts") or []
    aq = (combined.get("v3-wx-globalAirQuality") or {}).get("globalairquality")

    alerts = [
        {
            "headline": a.get("headlineText"),
            "severity": a.get("severity"),
            "area": a.get("areaName"),
            "source": f"{a.get('source', '')} - {a.get('officeName', '')}",
        }
        for a in alerts_raw
    ]

    air_quality = None
    if aq:
        primary = aq.get("primaryPollutant")
        details = (aq.get("pollutants") or {}).get(primary) if primary else None
        air_quality = {
            "aqi": aq.get("airQualityIndex"),
            "description": aq.get("airQualityCategory"),
            "primaryPollutant": primary,
            "primaryPollutantDetail": details,
        }

    return {
        "isNight": cond.get("dayOrNight") == "N",
        "sunrise": cond.get("sunriseTimeLocal"),
        "sunset": cond.get("sunsetTimeLocal"),
        "iconCode": cond.get("iconCode"),
        "conditionNarrative": cond.get("wxPhraseLong"),
        "cloudCover": cond.get("cloudCover"),
        "alerts": alerts,
        "airQuality": air_quality,
    }


def get_forecast_daily(
    latitude: float, longitude: float, units: Units = "metric", language: str = "en-US"
) -> list[dict[str, Any]]:
    """Fetch the 7-day daily forecast."""
    res = _get(
        "/v3/wx/forecast/daily/7day",
        {
            "geocode": f"{latitude},{longitude}",
            "language": language,
            "units": _UNIT_QUERY[units],
            "format": "json",
        },
    )
    res = res or {}
    days = res.get("dayOfWeek") or []
    daypart = (res.get("daypart") or [{}])[0] or {}

    forecast = []
    for i in range(len(days)):
        day_idx = i * 2
        night_idx = i * 2 + 1
        forecast.append(
            {
                "date": (res.get("validTimeLocal") or [None] * len(days))[i],
                "dayOfWeek": days[i],
                "high": (res.get("calendarDayTemperatureMax") or [None] * len(days))[i],
                "low": (res.get("calendarDayTemperatureMin") or [None] * len(days))[i],
                "narrative": (res.get("narrative") or [""] * len(days))[i],
                "dayDesc": _daypart_field(daypart, "wxPhraseLong", day_idx),
                "nightDesc": _daypart_field(daypart, "wxPhraseLong", night_idx),
                "precipChanceDay": _daypart_field(daypart, "precipChance", day_idx),
                "precipChanceNight": _daypart_field(daypart, "precipChance", night_idx),
                "precipType": _daypart_field(daypart, "precipType", day_idx)
                or _daypart_field(daypart, "precipType", night_idx),
                "totalPrecip": (res.get("qpf") or [None] * len(days))[i],
                "totalSnow": (res.get("qpfSnow") or [None] * len(days))[i],
                "iconCode": _daypart_field(daypart, "iconCode", day_idx),
                "sunrise": (res.get("sunriseTimeLocal") or [None] * len(days))[i],
                "sunset": (res.get("sunsetTimeLocal") or [None] * len(days))[i],
                "moonrise": (res.get("moonriseTimeLocal") or [None] * len(days))[i],
                "moonset": (res.get("moonsetTimeLocal") or [None] * len(days))[i],
                "moonPhase": (res.get("moonPhase") or [None] * len(days))[i],
                "moonPhaseCode": (res.get("moonPhaseCode") or [None] * len(days))[i],
            }
        )
    return forecast


def _daypart_field(daypart: dict[str, Any], field: str, index: int) -> Any:
    values = daypart.get(field)
    if not values or index >= len(values):
        return None
    return values[index]


def get_forecast_hourly(
    latitude: float,
    longitude: float,
    units: Units = "metric",
    language: str = "en-US",
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Fetch the hourly forecast (up to 48h ahead, default trimmed to 24h)."""
    res = _get(
        "/v3/wx/forecast/hourly/2day",
        {
            "geocode": f"{latitude},{longitude}",
            "language": language,
            "units": _UNIT_QUERY[units],
            "format": "json",
        },
    )
    res = res or {}
    times = res.get("validTimeLocal") or []
    count = min(hours, len(times))

    hourly = []
    for i in range(count):
        hourly.append(
            {
                "time": times[i],
                "temp": _at(res, "temperature", i),
                "feelsLike": _at(res, "temperatureFeelsLike", i),
                "desc": _at(res, "wxPhraseShort", i),
                "iconCode": _at(res, "iconCode", i),
                "precipChance": _at(res, "precipChance", i),
                "precipType": _at(res, "precipType", i),
                "qpfRain": _at(res, "qpfRain", i),
                "qpfSnow": _at(res, "qpfSnow", i),
                "humidity": _at(res, "relativeHumidity", i),
                "windSpeed": _at(res, "windSpeed", i),
                "windDir": _at(res, "windDirectionCardinal", i),
                "pressure": _at(res, "pressureMeanSeaLevel", i),
                "uvIndex": _at(res, "uvIndex", i),
                "cloudCover": _at(res, "cloudCover", i),
            }
        )
    return hourly


def get_rain_forecast(
    latitude: float,
    longitude: float,
    units: Units = "metric",
    language: str = "en-US",
    hours: int = 24,
) -> dict[str, Any]:
    """Precipitation-focused view: hourly chance/amount plus the 7-day rain summary."""
    hourly = get_forecast_hourly(latitude, longitude, units=units, language=language, hours=hours)
    daily = get_forecast_daily(latitude, longitude, units=units, language=language)
    return {"hourly": hourly, "daily": daily}


def get_dashboard(
    station_id: str, units: Units = "metric", language: str = "en-US"
) -> dict[str, Any]:
    """Everything needed for a one-screen overview: current conditions, extended
    conditions/alerts/AQ, today's sun & moon details, next 6h, and the 7-day outlook."""
    obs = get_current_observation(station_id, units=units)
    latitude, longitude = obs.get("latitude"), obs.get("longitude")

    extended = None
    if latitude and longitude:
        extended = get_extended_conditions(latitude, longitude, units=units, language=language)

    daily = get_forecast_daily(latitude, longitude, units=units, language=language) if latitude and longitude else []
    hourly = (
        get_forecast_hourly(latitude, longitude, units=units, language=language, hours=6)
        if latitude and longitude
        else []
    )

    return {
        "obs": obs,
        "extended": extended,
        "today": daily[0] if daily else None,
        "hourly": hourly,
        "daily": daily,
    }


def _at(res: dict[str, Any], field: str, index: int) -> Any:
    values = res.get(field)
    if not values or index >= len(values):
        return None
    return values[index]
