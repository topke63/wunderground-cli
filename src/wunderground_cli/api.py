"""Client for the weather API used by k-donn/plasmoid-wunderground.

The plasmoid does not call The Weather Company / Wunderground API directly;
it goes through a public Cloudflare Worker proxy (wps.mitchell-*.workers.dev)
that injects the real API key server-side. This client talks to the same
proxy, so no API key is required here either.
"""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
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


_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
_ATTEMPTS = 3

_client = httpx.Client(timeout=10.0)


def _api_host(exclude: set[str] | None = None) -> str:
    shards = [sh for sh in _HOST_SHARDS if sh not in (exclude or set())] or _HOST_SHARDS
    return f"https://wps.mitchell-{random.choice(shards)}.workers.dev"


def _fetch(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    try:
        return _client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise WundergroundAPIError(f"Network error contacting {url}: {exc}") from exc


def _get(path: str, params: dict[str, Any]) -> Any:
    """GET from the proxy, retrying on another shard after network errors and 5xx."""
    tried: set[str] = set()
    error: WundergroundAPIError | None = None
    for _ in range(_ATTEMPTS):
        host = _api_host(tried)
        tried.add(host.split("mitchell-")[1].split(".")[0])
        try:
            resp = _fetch(f"{host}{path}", params)
        except WundergroundAPIError as exc:
            error = exc
            continue
        if resp.status_code >= 500:
            error = WundergroundAPIError(
                f"Request to {path} failed: HTTP {resp.status_code}", resp.status_code
            )
            continue
        if resp.status_code != 200:
            raise WundergroundAPIError(
                f"Request to {path} failed: HTTP {resp.status_code}", resp.status_code
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise WundergroundAPIError(f"Could not parse response from {path}: {exc}") from exc
    assert error is not None
    raise error


def _absolute_pressure(sea_level: float | None, elevation: float | None, units: Units) -> float | None:
    """Convert the station's sea-level-adjusted pressure to absolute (station) pressure.

    The API only reports the sea-level value; undo the adjustment with the
    standard-atmosphere formula using the station elevation (metres for
    metric, feet otherwise).
    """
    if sea_level is None or elevation is None:
        return sea_level
    metres = elevation if units == "metric" else elevation * 0.3048
    absolute = sea_level * (1 - 2.25577e-5 * metres) ** 5.25588
    return round(absolute, 2 if units == "imperial" else 1)


def _aq_scale(country_code: str | None) -> str:
    return _AQ_SCALE_BY_COUNTRY.get((country_code or "").upper(), "EPA")


@dataclass
class Station:
    station_id: str
    address: str
    latitude: float
    longitude: float


def _stations(res: Any, id_key: str, name_key: str) -> list[Station]:
    loc = (res or {}).get("location") or {}
    ids = loc.get(id_key) or []
    return [
        Station(
            station_id=ids[i],
            address=_at(loc, name_key, i) or "",
            latitude=_at(loc, "latitude", i) or 0.0,
            longitude=_at(loc, "longitude", i) or 0.0,
        )
        for i in range(len(ids))
    ]


def search_stations(query: str, language: str = "en-US") -> list[Station]:
    """Search nearby PWS stations by free text (city, address, station id...)."""
    res = _get(
        "/v3/location/search",
        {"query": query, "locationType": "pws", "language": language, "format": "json"},
    )
    return _stations(res, "pwsId", "neighborhood")


def search_geocode(latitude: float, longitude: float) -> list[Station]:
    """Search PWS stations near a lat/lon coordinate."""
    res = _get(
        "/v3/location/near",
        {"geocode": f"{latitude},{longitude}", "product": "pws", "format": "json"},
    )
    return _stations(res, "stationId", "stationName")


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
        "pressure": _absolute_pressure(section.get("pressure"), section.get("elev"), units),
        "pressureSeaLevel": section.get("pressure"),
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
            "pollutants": list((aq.get("pollutants") or {}).values()),
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
                "date": _at(res, "validTimeLocal", i),
                "dayOfWeek": days[i],
                "high": _at(res, "calendarDayTemperatureMax", i),
                "low": _at(res, "calendarDayTemperatureMin", i),
                "narrative": _at(res, "narrative", i),
                "dayDesc": _at(daypart, "wxPhraseLong", day_idx),
                "nightDesc": _at(daypart, "wxPhraseLong", night_idx),
                "precipChanceDay": _at(daypart, "precipChance", day_idx),
                "precipChanceNight": _at(daypart, "precipChance", night_idx),
                "precipType": _at(daypart, "precipType", day_idx)
                or _at(daypart, "precipType", night_idx),
                "totalPrecip": _at(res, "qpf", i),
                "totalSnow": _at(res, "qpfSnow", i),
                "iconCode": _at(daypart, "iconCode", day_idx),
                "sunrise": _at(res, "sunriseTimeLocal", i),
                "sunset": _at(res, "sunsetTimeLocal", i),
                "moonrise": _at(res, "moonriseTimeLocal", i),
                "moonset": _at(res, "moonsetTimeLocal", i),
                "moonPhase": _at(res, "moonPhase", i),
                "moonPhaseCode": _at(res, "moonPhaseCode", i),
            }
        )
    return forecast


def get_forecast_hourly(
    latitude: float,
    longitude: float,
    units: Units = "metric",
    language: str = "en-US",
    hours: int = 24,
    elevation: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch the hourly forecast (up to 48h ahead, default trimmed to 24h).

    The forecast pressure is sea-level; pass the station `elevation` (metres for
    metric, feet otherwise, as reported by the observation) to get absolute pressure.
    """
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
                "pressure": _absolute_pressure(_at(res, "pressureMeanSeaLevel", i), elevation, units),
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


def get_aurora() -> dict[str, Any]:
    """NOAA SWPC planetary Kp index: latest observation plus the 3-hourly forecast."""
    resp = _fetch(_KP_URL)
    if resp.status_code != 200:
        raise WundergroundAPIError(f"NOAA Kp request failed: HTTP {resp.status_code}", resp.status_code)
    try:
        rows = resp.json()
    except ValueError as exc:
        raise WundergroundAPIError(f"Could not parse NOAA Kp response: {exc}") from exc

    entries = [
        {"time": r.get("time_tag"), "kp": float(r["kp"]), "kind": r.get("observed")}
        for r in rows
        if isinstance(r, dict) and r.get("kp") is not None
    ]
    past = [e for e in entries if e["kind"] in ("observed", "estimated")]
    return {
        "current": past[-1] if past else None,
        "forecast": [e for e in entries if e["kind"] == "predicted"][:16],
    }


def get_dashboard(
    station_id: str, units: Units = "metric", language: str = "en-US"
) -> dict[str, Any]:
    """Everything needed for a one-screen overview: current conditions, extended
    conditions/alerts/AQ, today's sun & moon details, next 6h, and the 7-day outlook.

    The observation is required; the other sections are fetched in parallel and
    degrade to empty with a message in `errors` if they fail.
    """
    obs = get_current_observation(station_id, units=units)
    latitude, longitude = obs.get("latitude"), obs.get("longitude")

    extended: dict[str, Any] | None = None
    daily: list[dict[str, Any]] = []
    hourly: list[dict[str, Any]] = []
    errors: list[str] = []

    if latitude is not None and longitude is not None:
        jobs = {
            "extended": lambda: get_extended_conditions(latitude, longitude, units, language),
            "daily": lambda: get_forecast_daily(latitude, longitude, units, language),
            "hourly": lambda: get_forecast_hourly(
                latitude, longitude, units, language, hours=6, elevation=obs.get("elevation")
            ),
        }
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {name: pool.submit(job) for name, job in jobs.items()}
        results: dict[str, Any] = {}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except WundergroundAPIError as exc:
                errors.append(f"{name}: {exc}")
        extended = results.get("extended")
        daily = results.get("daily") or []
        hourly = results.get("hourly") or []

    return {
        "obs": obs,
        "extended": extended,
        "today": daily[0] if daily else None,
        "hourly": hourly,
        "daily": daily,
        "errors": errors,
    }


def _at(res: dict[str, Any], field: str, index: int) -> Any:
    """Element `index` of a parallel-array field, or None if missing/short."""
    values = res.get(field)
    if not values or index >= len(values):
        return None
    return values[index]
