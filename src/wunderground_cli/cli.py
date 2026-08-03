"""Typer entrypoint for the `wu` command."""

from __future__ import annotations

import typer

from wunderground_cli import api, config, display

app = typer.Typer(help="Weather Underground PWS conditions and forecasts, from the terminal.")
station_app = typer.Typer(help="Find and manage PWS stations.")
config_app = typer.Typer(help="View and edit local CLI config.")
app.add_typer(station_app, name="station")
app.add_typer(config_app, name="config")


def _resolve_station(station: str | None) -> str:
    cfg = config.load()
    resolved = station or cfg.station_id
    if not resolved:
        display.print_error(
            "No station given and no default configured. "
            "Use --station or run 'wu station set <id>' first."
        )
        raise typer.Exit(1)
    return resolved


def _resolve_coords(cfg: config.Config, obs: dict) -> tuple[float, float]:
    lat = obs.get("latitude") or cfg.latitude
    lon = obs.get("longitude") or cfg.longitude
    return lat, lon


@station_app.command("search")
def station_search(query: str):
    """Search PWS stations by city, address, or station id."""
    try:
        stations = api.search_stations(query)
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)
    if not stations:
        display.print_error(f"No stations found for '{query}'.")
        raise typer.Exit(1)
    display.print_stations(stations)


@station_app.command("near")
def station_near(latitude: float, longitude: float):
    """Search PWS stations near a coordinate."""
    try:
        stations = api.search_geocode(latitude, longitude)
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)
    if not stations:
        display.print_error("No stations found near that coordinate.")
        raise typer.Exit(1)
    display.print_stations(stations)


@station_app.command("set")
def station_set(station_id: str):
    """Set the default station used when --station is omitted."""
    try:
        obs = api.get_current_observation(station_id)
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)

    cfg = config.load()
    cfg.station_id = station_id
    cfg.latitude = obs.get("latitude")
    cfg.longitude = obs.get("longitude")
    config.save(cfg)
    display.console.print(
        f"[green]Default station set to {station_id} "
        f"({obs.get('neighborhood')}, {cfg.latitude}, {cfg.longitude})[/green]"
    )


@config_app.command("show")
def config_show():
    """Print the current local config."""
    cfg = config.load()
    display.console.print(cfg)


@app.command()
def current(
    station: str = typer.Option(None, "--station", "-s", help="Station id (overrides config)."),
    units: str = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid"),
):
    """Show current conditions for a station."""
    cfg = config.load()
    station_id = _resolve_station(station)
    resolved_units = units or cfg.units

    try:
        obs = api.get_current_observation(station_id, units=resolved_units)
        lat, lon = _resolve_coords(cfg, obs)
        extended = None
        today = None
        if lat and lon:
            extended = api.get_extended_conditions(lat, lon, units=resolved_units, language=cfg.language)
            days = api.get_forecast_daily(lat, lon, units=resolved_units, language=cfg.language)
            today = days[0] if days else None
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)

    display.print_current(obs, resolved_units, extended, today)


@app.command()
def forecast(
    station: str = typer.Option(None, "--station", "-s", help="Station id (overrides config)."),
    units: str = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid"),
):
    """Show the 7-day forecast for a station's area."""
    cfg = config.load()
    station_id = _resolve_station(station)
    resolved_units = units or cfg.units

    try:
        obs = api.get_current_observation(station_id, units=resolved_units)
        lat, lon = _resolve_coords(cfg, obs)
        if not (lat and lon):
            display.print_error("Could not determine station coordinates.")
            raise typer.Exit(1)
        days = api.get_forecast_daily(lat, lon, units=resolved_units, language=cfg.language)
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)

    display.print_forecast(days, resolved_units)


@app.command()
def hourly(
    station: str = typer.Option(None, "--station", "-s", help="Station id (overrides config)."),
    units: str = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid"),
    hours: int = typer.Option(24, "--hours", "-n", help="Number of hours to show (max 48)."),
):
    """Show the hourly forecast for a station's area."""
    cfg = config.load()
    station_id = _resolve_station(station)
    resolved_units = units or cfg.units

    try:
        obs = api.get_current_observation(station_id, units=resolved_units)
        lat, lon = _resolve_coords(cfg, obs)
        if not (lat and lon):
            display.print_error("Could not determine station coordinates.")
            raise typer.Exit(1)
        hourly_data = api.get_forecast_hourly(
            lat, lon, units=resolved_units, language=cfg.language, hours=hours
        )
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)

    display.print_hourly(hourly_data, resolved_units)


@app.command()
def rain(
    station: str = typer.Option(None, "--station", "-s", help="Station id (overrides config)."),
    units: str = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid"),
    hours: int = typer.Option(24, "--hours", "-n", help="Number of hours to show (max 48)."),
):
    """Show a precipitation-focused forecast: hourly chance/amount plus the 7-day outlook."""
    cfg = config.load()
    station_id = _resolve_station(station)
    resolved_units = units or cfg.units

    try:
        obs = api.get_current_observation(station_id, units=resolved_units)
        lat, lon = _resolve_coords(cfg, obs)
        if not (lat and lon):
            display.print_error("Could not determine station coordinates.")
            raise typer.Exit(1)
        rain_data = api.get_rain_forecast(
            lat, lon, units=resolved_units, language=cfg.language, hours=hours
        )
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)

    display.print_rain(rain_data["hourly"], rain_data["daily"], resolved_units)


@app.command()
def dashboard(
    station: str = typer.Option(None, "--station", "-s", help="Station id (overrides config)."),
    units: str = typer.Option(None, "--units", "-u", help="metric | imperial | hybrid"),
):
    """One-screen overview: current conditions, sun/moon, next hours, and 7-day outlook."""
    cfg = config.load()
    station_id = _resolve_station(station)
    resolved_units = units or cfg.units

    try:
        data = api.get_dashboard(station_id, units=resolved_units, language=cfg.language)
    except api.WundergroundAPIError as exc:
        display.print_error(str(exc))
        raise typer.Exit(1)

    display.print_dashboard(data, resolved_units)


if __name__ == "__main__":
    app()
