import httpx
import pytest

from wunderground_cli import api, config


def _resp(status=200, json=None):
    return httpx.Response(status, json=json, request=httpx.Request("GET", "http://x"))


def test_absolute_pressure_metric_and_imperial():
    assert api._absolute_pressure(1022.69, 76.2, "metric") == pytest.approx(1013.5, abs=0.1)
    assert api._absolute_pressure(30.2, 250, "imperial") == pytest.approx(29.95, abs=0.02)
    assert api._absolute_pressure(None, 10, "metric") is None
    assert api._absolute_pressure(1000.0, None, "metric") == 1000.0


def test_current_observation_maps_units_section(monkeypatch):
    payload = {"observations": [{"stationID": "X", "lat": 1.0, "lon": 2.0, "humidity": 50,
                                 "metric": {"temp": 10, "pressure": 1013.25, "elev": 0}}]}
    monkeypatch.setattr(api, "_get", lambda path, params: payload)
    obs = api.get_current_observation("X")
    assert obs["temp"] == 10 and obs["pressure"] == pytest.approx(1013.25, abs=0.06)
    assert obs["pressureSeaLevel"] == 1013.25 and obs["latitude"] == 1.0


def test_no_observation_raises(monkeypatch):
    monkeypatch.setattr(api, "_get", lambda path, params: {"observations": []})
    with pytest.raises(api.WundergroundAPIError):
        api.get_current_observation("X")


def test_get_retries_on_5xx_then_succeeds(monkeypatch):
    calls = iter([_resp(502), _resp(200, {"ok": True})])
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: next(calls))
    assert api._get("/p", {}) == {"ok": True}


def test_get_does_not_retry_4xx(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: calls.append(url) or _resp(404))
    with pytest.raises(api.WundergroundAPIError) as exc:
        api._get("/p", {})
    assert exc.value.status == 404 and len(calls) == 1


def test_get_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: _resp(503))
    with pytest.raises(api.WundergroundAPIError):
        api._get("/p", {})


def test_station_search_parses_parallel_arrays(monkeypatch):
    res = {"location": {"pwsId": ["A", "B"], "neighborhood": ["Aa"], "latitude": [1, 2], "longitude": [3, 4]}}
    monkeypatch.setattr(api, "_get", lambda path, params: res)
    stations = api.search_stations("q")
    assert [s.station_id for s in stations] == ["A", "B"]
    assert stations[1].address == "" and stations[1].longitude == 4


def test_daily_forecast_daypart_indexing(monkeypatch):
    res = {"dayOfWeek": ["Mon", "Tue"], "calendarDayTemperatureMax": [10, 12],
           "daypart": [{"wxPhraseLong": ["d0", "n0", "d1", "n1"], "precipChance": [10, 20, 30, 40]}]}
    monkeypatch.setattr(api, "_get", lambda path, params: res)
    days = api.get_forecast_daily(0.0, 0.0)
    assert days[1]["dayDesc"] == "d1" and days[1]["nightDesc"] == "n1"
    assert days[1]["precipChanceDay"] == 30 and days[1]["high"] == 12 and days[0]["low"] is None


def test_dashboard_degrades_and_handles_zero_coords(monkeypatch):
    monkeypatch.setattr(api, "get_current_observation", lambda s, units: {"latitude": 0.0, "longitude": 0.0})
    monkeypatch.setattr(api, "get_extended_conditions", lambda *a: (_ for _ in ()).throw(api.WundergroundAPIError("boom")))
    monkeypatch.setattr(api, "get_forecast_daily", lambda *a: [{"dayOfWeek": "Mon"}])
    monkeypatch.setattr(api, "get_forecast_hourly", lambda *a, **k: [])
    d = api.get_dashboard("X")
    assert d["extended"] is None and d["today"]["dayOfWeek"] == "Mon"
    assert d["errors"] == ["extended: boom"]


def test_aurora_splits_current_and_forecast(monkeypatch):
    rows = [{"time_tag": "t1", "kp": "2.0", "observed": "observed"},
            {"time_tag": "t2", "kp": "3.0", "observed": "estimated"},
            {"time_tag": "t3", "kp": "5.0", "observed": "predicted"}]
    monkeypatch.setattr(api, "_fetch", lambda url, params=None: _resp(200, rows))
    data = api.get_aurora()
    assert data["current"]["kp"] == 3.0 and [e["kp"] for e in data["forecast"]] == [5.0]


def test_config_corrupt_file_raises(tmp_path, monkeypatch):
    f = tmp_path / "config.json"
    f.write_text("{not json")
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    with pytest.raises(config.ConfigError):
        config.load()


def test_config_ignores_unknown_keys(tmp_path, monkeypatch):
    f = tmp_path / "config.json"
    f.write_text('{"units": "imperial", "junk": 1}')
    monkeypatch.setattr(config, "CONFIG_FILE", f)
    assert config.load().units == "imperial"
