"""Rich-based rendering for observations, forecasts, and station lists."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

_UNIT_LABELS = {
    "metric": {"temp": "C", "wind": "km/h", "pressure": "mb", "precip": "mm"},
    "imperial": {"temp": "F", "wind": "mph", "pressure": "inHg", "precip": "in"},
    "hybrid": {"temp": "C", "wind": "mph", "pressure": "mb", "precip": "mm"},
}

_MOON_EMOJI = {
    "N": "🌑",
    "WXC": "🌒",
    "FQ": "🌓",
    "WXG": "🌔",
    "F": "🌕",
    "WNG": "🌖",
    "LQ": "🌗",
    "WNC": "🌘",
}


def _fmt_time(value: Any, fmt: str = "%H:%M") -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime(fmt)
    except ValueError:
        return str(value)


def _moon_line(day: dict[str, Any] | None) -> str | None:
    if not day or not day.get("moonPhase"):
        return None
    emoji = _MOON_EMOJI.get(day.get("moonPhaseCode") or "", "")
    return (
        f"Moon: {emoji} {day.get('moonPhase')}  "
        f"(rise {_fmt_time(day.get('moonrise'))} / set {_fmt_time(day.get('moonset'))})"
    )


def print_stations(stations: list) -> None:
    table = Table(title="Stations")
    table.add_column("Station ID")
    table.add_column("Address / Name")
    table.add_column("Latitude")
    table.add_column("Longitude")
    for s in stations:
        table.add_row(s.station_id, s.address, f"{s.latitude:.4f}", f"{s.longitude:.4f}")
    console.print(table)


def print_current(
    obs: dict[str, Any],
    units: str,
    extended: dict[str, Any] | None = None,
    today: dict[str, Any] | None = None,
) -> None:
    labels = _UNIT_LABELS[units]
    title = obs.get("neighborhood") or obs.get("stationID") or "Current Conditions"
    lines = [
        f"[bold]{obs.get('temp')}°{labels['temp']}[/bold]"
        + (f"  (feels like {obs.get('heatIndex') or obs.get('windChill')}°{labels['temp']})" if obs.get("heatIndex") or obs.get("windChill") else ""),
    ]
    if extended and extended.get("conditionNarrative"):
        lines.append(extended["conditionNarrative"])

    lines += [
        f"Humidity: {obs.get('humidity')}%",
        f"Wind: {obs.get('windSpeed')} {labels['wind']} (gusts {obs.get('windGust')} {labels['wind']})",
        f"Pressure: {obs.get('pressure')} {labels['pressure']}",
        f"Precip rate/total: {obs.get('precipRate')}/{obs.get('precipTotal')} {labels['precip']}",
        f"Dew point: {obs.get('dewpt')}°{labels['temp']}",
        f"UV index: {obs.get('uv')}",
        f"Observed: {obs.get('obsTimeLocal')}",
        f"Station: {obs.get('stationID')} ({obs.get('latitude')}, {obs.get('longitude')})",
    ]

    sunrise = (extended or {}).get("sunrise") or (today or {}).get("sunrise")
    sunset = (extended or {}).get("sunset") or (today or {}).get("sunset")
    if sunrise or sunset:
        lines.append(f"☀ Sunrise/Sunset: {_fmt_time(sunrise)} / {_fmt_time(sunset)}")

    moon_line = _moon_line(today)
    if moon_line:
        lines.append(moon_line)

    if extended:
        if extended.get("airQuality"):
            aq = extended["airQuality"]
            lines.append(f"Air quality: {aq.get('aqi')} ({aq.get('description')})")
        for alert in extended.get("alerts") or []:
            lines.append(f"[bold red]ALERT[/bold red]: {alert.get('headline')}")

    console.print(Panel("\n".join(lines), title=title))


def print_forecast(days: list[dict[str, Any]], units: str) -> None:
    labels = _UNIT_LABELS[units]
    table = Table(title="7-Day Forecast")
    table.add_column("Day")
    table.add_column(f"High ({labels['temp']})")
    table.add_column(f"Low ({labels['temp']})")
    table.add_column("Day")
    table.add_column("Night")
    table.add_column("Precip % (D/N)")
    table.add_column("Sun")
    table.add_column("Moon")

    for day in days:
        table.add_row(
            str(day.get("dayOfWeek")),
            str(day.get("high")),
            str(day.get("low")),
            str(day.get("dayDesc") or "-"),
            str(day.get("nightDesc") or "-"),
            f"{day.get('precipChanceDay', '-')}/{day.get('precipChanceNight', '-')}",
            f"{_fmt_time(day.get('sunrise'))}/{_fmt_time(day.get('sunset'))}",
            f"{_MOON_EMOJI.get(day.get('moonPhaseCode') or '', '')} {day.get('moonPhase') or '-'}",
        )
    console.print(table)


def print_hourly(hours: list[dict[str, Any]], units: str) -> None:
    labels = _UNIT_LABELS[units]
    table = Table(title="Hourly Forecast")
    table.add_column("Time")
    table.add_column(f"Temp ({labels['temp']})")
    table.add_column("Feels Like")
    table.add_column("Conditions")
    table.add_column("Precip %")
    table.add_column("Wind")
    table.add_column("Humidity")

    for hour in hours:
        table.add_row(
            _fmt_time(hour.get("time"), "%a %H:%M"),
            str(hour.get("temp")),
            str(hour.get("feelsLike")),
            str(hour.get("desc") or "-"),
            str(hour.get("precipChance", "-")),
            f"{hour.get('windSpeed', '-')} {labels['wind']} {hour.get('windDir', '')}".strip(),
            f"{hour.get('humidity', '-')}%",
        )
    console.print(table)


def print_rain(hourly: list[dict[str, Any]], daily: list[dict[str, Any]], units: str) -> None:
    labels = _UNIT_LABELS[units]

    hourly_table = Table(title="Hourly Precipitation")
    hourly_table.add_column("Time")
    hourly_table.add_column("Chance %")
    hourly_table.add_column(f"Rain ({labels['precip']})")
    hourly_table.add_column(f"Snow ({labels['precip']})")
    hourly_table.add_column("Type")

    any_precip = False
    for hour in hourly:
        chance = hour.get("precipChance") or 0
        rain = hour.get("qpfRain") or 0
        snow = hour.get("qpfSnow") or 0
        if chance or rain or snow:
            any_precip = True
        style = "bold cyan" if chance and chance >= 50 else None
        hourly_table.add_row(
            _fmt_time(hour.get("time"), "%a %H:%M"),
            str(chance),
            str(rain),
            str(snow),
            str(hour.get("precipType") or "-"),
            style=style,
        )
    console.print(hourly_table)
    if not any_precip:
        console.print("[dim]No precipitation expected in this window.[/dim]")

    daily_table = Table(title="Daily Precipitation Outlook")
    daily_table.add_column("Day")
    daily_table.add_column("Chance % (D/N)")
    daily_table.add_column(f"Total Rain ({labels['precip']})")
    daily_table.add_column(f"Total Snow ({labels['precip']})")
    daily_table.add_column("Type")

    for day in daily:
        daily_table.add_row(
            str(day.get("dayOfWeek")),
            f"{day.get('precipChanceDay', '-')}/{day.get('precipChanceNight', '-')}",
            str(day.get("totalPrecip") if day.get("totalPrecip") is not None else "-"),
            str(day.get("totalSnow") if day.get("totalSnow") is not None else "-"),
            str(day.get("precipType") or "-"),
        )
    console.print(daily_table)


def print_dashboard(dashboard: dict[str, Any], units: str) -> None:
    """One-screen overview: current conditions + sun/moon, next few hours, 7-day outlook."""
    print_current(dashboard["obs"], units, dashboard.get("extended"), dashboard.get("today"))
    if dashboard.get("hourly"):
        print_hourly(dashboard["hourly"], units)
    if dashboard.get("daily"):
        print_forecast(dashboard["daily"], units)


def print_error(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")
