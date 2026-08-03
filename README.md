# wunderground-cli

A Linux CLI port of [k-donn/plasmoid-wunderground](https://github.com/k-donn/plasmoid-wunderground),
the KDE Plasma widget for Weather Underground personal weather stations (PWS).

It talks to the same public proxy the plasmoid uses (a Cloudflare Worker in front of
The Weather Company / Wunderground's PWS API), so **no API key is required**.

## Install

```bash
pipx install -e .
```

This installs the `wu` command globally (editable, so code changes apply without reinstalling).

## Usage

```bash
# Find a station near you
wu station search "Boston"
wu station near 42.36 -71.05

# Remember a default station so you don't have to pass --station every time
wu station set KMABOSTO123

# Current conditions
wu current
wu current --station KMABOSTO123 --units imperial

# 7-day forecast
wu forecast

# Hourly forecast (default 24h, up to 48h)
wu hourly
wu hourly --hours 12

# Precipitation-focused forecast: hourly chance/amount + 7-day rain outlook
wu rain
wu rain --hours 12

# One-screen overview: current conditions, sun/moon, next hours, 7-day outlook
wu dashboard

# Inspect local config (~/.config/wunderground-cli/config.json)
wu config show
```

Units: `metric` (default), `imperial`, or `hybrid` (UK-style: Celsius + mph).

Current conditions and the 7-day forecast both include sunrise/sunset and moon
phase (with rise/set times).

## Status

Core commands (station search/near/set, current, forecast, hourly, rain, dashboard)
work end-to-end. Not yet ported from the original plasmoid: air quality detail
view and the NOAA Kp-index (aurora) panel.

## Project layout

```
src/wunderground_cli/
  api.py       # HTTP client for the weather proxy
  config.py    # local JSON config (default station, units)
  display.py   # rich terminal rendering
  cli.py       # Typer commands (`wu ...`)
```
