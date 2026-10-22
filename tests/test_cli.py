import json

from typer.testing import CliRunner

from wunderground_cli import api, cli, config

runner = CliRunner()
OBS = {"stationID": "X", "neighborhood": "Town", "latitude": 1.0, "longitude": 2.0, "temp": 5, "pressure": 1000}


def _cfg(tmp_path, monkeypatch, **data):
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"station_id": "X", **data}))
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    return f


def test_current_json(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "get_current_observation", lambda s, units: OBS)
    monkeypatch.setattr(api, "get_extended_conditions", lambda *a, **k: {"alerts": []})
    monkeypatch.setattr(api, "get_forecast_daily", lambda *a, **k: [{"dayOfWeek": "Mon"}])
    result = runner.invoke(cli.app, ["current", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["obs"]["temp"] == 5


def test_invalid_units_rejected(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["current", "--units", "kelvin"])
    assert result.exit_code == 1 and "Invalid units" in result.output


def test_no_station_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.json")
    result = runner.invoke(cli.app, ["current"])
    assert result.exit_code == 1 and "No station" in result.output


def test_corrupt_config_is_clean_error(tmp_path, monkeypatch):
    f = _cfg(tmp_path, monkeypatch)
    f.write_text("oops")
    result = runner.invoke(cli.app, ["current"])
    assert result.exit_code == 1 and "Could not read" in result.output


def test_config_set_units(tmp_path, monkeypatch):
    f = _cfg(tmp_path, monkeypatch)
    assert runner.invoke(cli.app, ["config", "set", "--units", "imperial"]).exit_code == 0
    assert json.loads(f.read_text())["units"] == "imperial"
    assert runner.invoke(cli.app, ["config", "set", "--units", "bad"]).exit_code == 1


def test_api_error_exits_cleanly(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    def boom(*a, **k):
        raise api.WundergroundAPIError("down")
    monkeypatch.setattr(api, "get_current_observation", boom)
    result = runner.invoke(cli.app, ["forecast"])
    assert result.exit_code == 1 and "down" in result.output


def test_air_and_aurora_render(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "get_current_observation", lambda s, units: OBS)
    aq = {"aqi": 27, "description": "Good", "primaryPollutant": "O3",
          "pollutants": [{"name": "O3", "phrase": "Ozone", "amount": 5, "unit": "ug", "index": 27, "category": "Good"}]}
    monkeypatch.setattr(api, "get_extended_conditions", lambda *a, **k: {"airQuality": aq})
    assert "Ozone" in runner.invoke(cli.app, ["air"]).output
    monkeypatch.setattr(api, "get_aurora", lambda: {"current": {"kp": 4.0, "kind": "observed", "time": "2026-01-01T00:00:00"},
                                                    "forecast": [{"kp": 5.0, "kind": "predicted", "time": "2026-01-01T03:00:00"}]})
    out = runner.invoke(cli.app, ["aurora"]).output
    assert "Current Kp" in out and "Forecast" in out
