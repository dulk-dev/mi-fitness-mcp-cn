import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import (
    MiFitnessCloudAdapter,
    _is_authentication_error,
)


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


def test_optional_number_helpers():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._optional_float(0) is None
    assert adapter._optional_float("1.5") == 1.5
    assert adapter._optional_int(0) is None
    assert adapter._optional_int("7") == 7


def test_parse_value_dict_and_json():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    assert adapter._parse_value({"value": {"steps": 1}}) == {"steps": 1}
    assert adapter._parse_value({"value": '{"steps": 2}'}) == {"steps": 2}


def test_record_datetime_uses_zone_offset():
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    dt = adapter._record_datetime({"time": 0, "zone_offset": 10800})
    assert dt.isoformat().startswith("1970-01-01T03:00:00")


@pytest.mark.asyncio
async def test_iter_daily_activity_aggregates_steps_and_calories(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1")
    adapter._connected = True
    adapter._client = object()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "steps":
            return [
                {
                    "time": 1743467400,
                    "zone_offset": 0,
                    "value": '{"steps": 10, "distance": 8, "calories": 1}',
                },
                {
                    "time": 1743467460,
                    "zone_offset": 0,
                    "value": '{"steps": 20, "distance": 16, "calories": 2}',
                },
            ]
        if key == "calories":
            return [
                {"time": 1743467400, "zone_offset": 0, "value": '{"calories": 5}'},
                {"time": 1743467460, "zone_offset": 0, "value": '{"calories": 7}'},
            ]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    items = await _collect(adapter.iter_daily_activity("2025-04-01", "2025-04-01"))

    assert len(items) == 1
    assert items[0].steps == 30
    assert items[0].distance_m == 24
    assert items[0].active_kcal == 12


@pytest.mark.asyncio
async def test_fetch_key_rejects_repeated_pagination_cursor(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._client = object()

    async def fake_request(base_url, api_path, payload):
        return {"data_list": [], "has_more": True, "next_key": "same"}

    monkeypatch.setattr(adapter, "_request", fake_request)
    with pytest.raises(RuntimeError, match="cursor loop"):
        await adapter._fetch_key("steps", "2026-07-06", "2026-07-12")


@pytest.mark.asyncio
async def test_connect_failure_closes_client(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="bad", region="cn")

    async def failed_login(user_id, pass_token):
        raise RuntimeError("invalid credentials")

    monkeypatch.setattr(adapter, "_login_with_token", failed_login)
    assert await adapter.connect() is False
    assert adapter._client is None
    assert "invalid credentials" in adapter.last_error


@pytest.mark.asyncio
async def test_iter_sleep_and_spo2_fetch_watch_keys(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._connected = True
    adapter._client = object()
    fetched: list[str] = []

    async def fake_fetch(key, start_date, end_date, region=None):
        fetched.append(key)
        if key == "watch_night_sleep":
            return [
                {
                    "sid": "s1",
                    "key": "watch_night_sleep",
                    "time": 1791244800,
                    "value": {
                        "bedtime": 1791227520,
                        "wake_up_time": 1791245100,
                        "duration": 293,
                        "sleep_awake_duration": 0,
                    },
                }
            ]
        if key == "single_spo2":
            return [
                {
                    "time": 1791242130,
                    "value": {"time": 1791242130, "spo2": 96},
                }
            ]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)

    sessions = await _collect(adapter.iter_sleep_sessions("2026-10-04", "2026-10-07"))
    assert fetched == ["sleep", "watch_night_sleep"]
    assert len(sessions) == 1
    session = sessions[0]
    assert session.timezone == "Asia/Shanghai"
    assert session.duration_minutes == 293
    assert session.time_awake_minutes == 0
    assert session.start_at.isoformat() == "2026-10-06T03:12:00+08:00"
    assert session.end_at.isoformat() == "2026-10-06T08:05:00+08:00"

    spo2 = await _collect(adapter.iter_spo2("2026-10-04", "2026-10-07"))
    assert fetched == ["sleep", "watch_night_sleep", "spo2", "single_spo2"]
    assert len(spo2) == 1
    assert spo2[0].spo2_pct == 96


def test_authentication_error_detection():
    assert _is_authentication_error(401, "denied")
    assert _is_authentication_error(0, "session expired")
    assert _is_authentication_error(-10001, "unknown")
    assert not _is_authentication_error(500, "temporary server failure")
