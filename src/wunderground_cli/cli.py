"""Typer entrypoint for the `wu` command."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, NoReturn

import typer

from wunderground_cli import api, config, display

app = typer.Typer(help="Weather Underground PWS conditions and forecasts, from the terminal.")
station_app = typer.Typer(help="Find and manage PWS stations.")
config_app = typer.Typer(help="View and edit local CLI config.")
app.add_typer(station_app, name="station")
app.add_typer(config_app, name="config")

StationOpt = typer.Option(None, "--station", "-s", help="Station id (overrides config).")
UnitsOpt = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid")
HoursOpt = typer.Option(24, "--hours", "-n", min=1, max=48, help="Number of hours to show (max 48).")
JsonOpt = typer.Option(False, "--json", help="Print raw JSON instead of formatted output.")


def _fail(message: str) -> NoReturn:
    display.print_error(message)
    raise typer.Exit(1)


def _emit_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=asdict))


def _load_config() -> config.Config:
    try:
        return config.load()
    except config.ConfigError as exc:
        _fail(str(exc))


def _check_units(units: str) -> str:
    if units not in config.VALID_UNITS:
        _fail(f"Invalid units '{units}'. Choose one of: {', '.join(config.VALID_UNITS)}.")
    return units


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run an API call, turning API errors into a clean CLI failure."""
    try:
        return fn(*args, **kwargs)
    except api.WundergroundAPIError as exc:
        _fail(str(exc))


@dataclass
class Context:
    cfg: config.Config
    station_id: str
    units: str


def _context(station: str | None, units: str | None) -> Context:
    cfg = _load_config()
    station_id = station or cfg.station_id
    if not station_id:
        _fail(
            "No station given and no default configured. "
            "Use --station or run 'wu station set <id>' first."
        )
    return Context(cfg, station_id, _check_units(units or cfg.units))


def _located(ctx: Context) -> tuple[dict, float, float]:
    """Fetch the observation and resolve coordinates, failing if none are available."""
    obs = _call(api.get_current_observation, ctx.station_id, units=ctx.units)
    lat, lon = obs.get("latitude"), obs.get("longitude")
    if lat is None or lon is None:
        lat, lon = ctx.cfg.latitude, ctx.cfg.longitude
    if lat is None or lon is None:
        _fail("Could not determine station coordinates.")
    return obs, lat, lon


@station_app.command("search")
def station_search(query: str, as_json: bool = JsonOpt):
    """Search PWS stations by city, address, or station id."""
    stations = _call(api.search_stations, query)
    if not stations:
        _fail(f"No stations found for '{query}'.")
    if as_json:
        return _emit_json(stations)
    display.print_stations(stations)


@station_app.command("near")
def station_near(latitude: float, longitude: float, as_json: bool = JsonOpt):
    """Search PWS stations near a coordinate."""
    stations = _call(api.search_geocode, latitude, longitude)
    if not stations:
        _fail("No stations found near that coordinate.")
    if as_json:
        return _emit_json(stations)
    display.print_stations(stations)


@station_app.command("set")
def station_set(station_id: str):
    """Set the default station used when --station is omitted."""
    obs = _call(api.get_current_observation, station_id)
    cfg = _load_config()
    cfg.station_id = station_id
    cfg.latitude = obs.get("latitude")
    cfg.longitude = obs.get("longitude")
    config.save(cfg)
    display.console.print(
        f"[green]Default station set to {station_id} "
        f"({obs.get('neighborhood')}, {cfg.latitude}, {cfg.longitude})[/green]"
    )


@config_app.command("show")
def config_show(as_json: bool = JsonOpt):
    """Print the current local config."""
    cfg = _load_config()
    if as_json:
        return _emit_json(asdict(cfg))
    display.console.print(cfg)


@config_app.command("set")
def config_set(
    units: str = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid"),
    language: str = typer.Option(None, "--language", "-l", help="Locale, e.g. en-US or de-DE."),
):
    """Change default units and/or language."""
    if units is None and language is None:
        _fail("Nothing to change. Pass --units and/or --language.")
    cfg = _load_config()
    if units is not None:
        cfg.units = _check_units(units)
    if language is not None:
        cfg.language = language
    config.save(cfg)
    display.console.print(f"[green]Saved:[/green] units={cfg.units}, language={cfg.language}")


@app.command()
def current(station: str = StationOpt, units: str = UnitsOpt, as_json: bool = JsonOpt):
    """Show current conditions for a station."""
    ctx = _context(station, units)
    obs = _call(api.get_current_observation, ctx.station_id, units=ctx.units)
    lat, lon = obs.get("latitude"), obs.get("longitude")
    if lat is None or lon is None:
        lat, lon = ctx.cfg.latitude, ctx.cfg.longitude

    extended = today = None
    if lat is not None and lon is not None:
        extended = _call(api.get_extended_conditions, lat, lon, units=ctx.units, language=ctx.cfg.language)
        days = _call(api.get_forecast_daily, lat, lon, units=ctx.units, language=ctx.cfg.language)
        today = days[0] if days else None

    if as_json:
        return _emit_json({"obs": obs, "extended": extended, "today": today})
    display.print_current(obs, ctx.units, extended, today)


@app.command()
def forecast(station: str = StationOpt, units: str = UnitsOpt, as_json: bool = JsonOpt):
    """Show the 7-day forecast for a station's area."""
    ctx = _context(station, units)
    _, lat, lon = _located(ctx)
    days = _call(api.get_forecast_daily, lat, lon, units=ctx.units, language=ctx.cfg.language)
    if as_json:
        return _emit_json(days)
    display.print_forecast(days, ctx.units)


@app.command()
def hourly(
    station: str = StationOpt, units: str = UnitsOpt, hours: int = HoursOpt, as_json: bool = JsonOpt
):
    """Show the hourly forecast for a station's area."""
    ctx = _context(station, units)
    obs, lat, lon = _located(ctx)
    data = _call(
        api.get_forecast_hourly,
        lat,
        lon,
        units=ctx.units,
        language=ctx.cfg.language,
        hours=hours,
        elevation=obs.get("elevation"),
    )
    if as_json:
        return _emit_json(data)
    display.print_hourly(data, ctx.units)


@app.command()
def rain(
    station: str = StationOpt, units: str = UnitsOpt, hours: int = HoursOpt, as_json: bool = JsonOpt
):
    """Show a precipitation-focused forecast: hourly chance/amount plus the 7-day outlook."""
    ctx = _context(station, units)
    _, lat, lon = _located(ctx)
    data = _call(
        api.get_rain_forecast, lat, lon, units=ctx.units, language=ctx.cfg.language, hours=hours
    )
    if as_json:
        return _emit_json(data)
    display.print_rain(data["hourly"], data["daily"], ctx.units)


@app.command()
def air(station: str = StationOpt, units: str = UnitsOpt, as_json: bool = JsonOpt):
    """Show air quality: overall index and per-pollutant readings."""
    ctx = _context(station, units)
    _, lat, lon = _located(ctx)
    extended = _call(
        api.get_extended_conditions, lat, lon, units=ctx.units, language=ctx.cfg.language
    )
    aq = extended.get("airQuality")
    if not aq:
        _fail("No air quality data available for this location.")
    if as_json:
        return _emit_json(aq)
    display.print_air_quality(aq)


@app.command()
def aurora(as_json: bool = JsonOpt):
    """Show the NOAA planetary Kp index (geomagnetic / aurora activity) and its forecast."""
    data = _call(api.get_aurora)
    if as_json:
        return _emit_json(data)
    display.print_aurora(data)


@app.command()
def dashboard(station: str = StationOpt, units: str = UnitsOpt, as_json: bool = JsonOpt):
    """One-screen overview: current conditions, sun/moon, next hours, and 7-day outlook."""
    ctx = _context(station, units)
    data = _call(api.get_dashboard, ctx.station_id, units=ctx.units, language=ctx.cfg.language)
    if as_json:
        return _emit_json(data)
    display.print_dashboard(data, ctx.units)


if __name__ == "__main__":
    app()
