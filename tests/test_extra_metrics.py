from datetime import datetime, timedelta, timezone

import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import (
    SUPPORTED_DATA_TYPES,
    MiFitnessCloudAdapter,
)
from mi_fitness_mcp.api import DATA_TYPES
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

# 2026-10-06 08:00:00+08
DAY = 1791244800
TZ8 = timezone(timedelta(hours=8))


async def _collect(async_iterable):
    items = []
    async for item in async_iterable:
        items.append(item)
    return items


def _adapter() -> MiFitnessCloudAdapter:
    adapter = MiFitnessCloudAdapter(user_id="u1", pass_token="p1", region="cn")
    adapter._connected = True
    adapter._client = object()
    return adapter


def _item(value: dict, time: int = DAY, zone_offset: int = 28800) -> dict:
    return {
        "time": time,
        "zone_offset": zone_offset,
        "zone_name": "Asia/Shanghai",
        "sid": "watch",
        "value": value,
    }


def test_supported_types_match_api():
    assert list(SUPPORTED_DATA_TYPES) == DATA_TYPES
    for name in ("pai", "valid_stand", "menstruation", "training_load", "intensity"):
        assert name in DATA_TYPES


@pytest.mark.asyncio
async def test_fetch_aggregated_pages_with_next_key(monkeypatch):
    adapter = _adapter()
    seen = []

    async def fake_request(base_url, api_path, payload):
        seen.append((api_path, dict(payload)))
        if payload.get("next_key") == "page-2":
            return {"data_list": [{"time": 2, "value": "{}"}], "has_more": False}
        return {
            "data_list": [{"time": 1, "value": "{}"}],
            "has_more": True,
            "next_key": "page-2",
        }

    monkeypatch.setattr(adapter, "_request", fake_request)
    rows = await adapter._fetch_aggregated("sleep", "2026-10-06", "2026-10-06")

    assert [row["time"] for row in rows] == [1, 2]
    assert seen[0][0] == "/app/v1/data/get_aggregated_fitness_data_by_time"
    assert seen[0][1]["key"] == "sleep"
    assert seen[0][1]["tag"] == "daily_report"
    assert "start_time" in seen[0][1] and "end_time" in seen[0][1]
    assert seen[0][1]["limit"] == 100
    assert "next_key" not in seen[0][1]
    assert seen[1][1]["next_key"] == "page-2"


@pytest.mark.asyncio
async def test_fetch_aggregated_rejects_cursor_loop(monkeypatch):
    adapter = _adapter()

    async def fake_request(base_url, api_path, payload):
        return {"data_list": [], "has_more": True, "next_key": "same"}

    monkeypatch.setattr(adapter, "_request", fake_request)
    with pytest.raises(RuntimeError, match="cursor loop"):
        await adapter._fetch_aggregated("pai", "2026-10-01", "2026-10-06")


@pytest.mark.asyncio
async def test_iter_extra_metrics_from_mocked_fetches(monkeypatch):
    adapter = _adapter()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "pai":
            return [
                _item(
                    {
                        "date_time": DAY,
                        "daily_pai": 12.5,
                        "total_pai": 80,
                        "low_zone_pai": 4,
                        "medium_zone_pai": 5.5,
                        "high_zone_pai": 3,
                    }
                )
            ]
        if key == "valid_stand":
            return [_item({"start_time": DAY, "end_time": DAY + 3600})]
        if key == "menstruation":
            return [
                _item({"status": 1, "date_time": DAY, "update_time": DAY + 60}),
                _item({"status": 9, "date_time": DAY}),
                _item({"status": 3, "date_time": DAY + 86400}),
            ]
        if key == "training_load":
            return [
                _item(
                    {
                        "date_time": DAY,
                        "current_day_train_load": 40,
                        "wtl_sum": 210,
                        "wtl_sum_optimal_min": 150,
                        "wtl_sum_optimal_max": 300,
                        "wtl_sum_overreaching": 450,
                    }
                )
            ]
        if key == "intensity":
            return [_item({"time": DAY}), _item({"time": DAY + 1800})]
        return []

    async def fake_aggregated(key, start_date, end_date, tag="daily_report", region=None):
        assert tag == "daily_report"
        if key == "valid_stand":
            return [_item({"count": 8})]
        if key == "intensity":
            return [_item({"duration": 46})]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    monkeypatch.setattr(adapter, "_fetch_aggregated", fake_aggregated)

    pai = await _collect(adapter.iter_pai("2026-10-06", "2026-10-06"))
    assert len(pai) == 1
    assert pai[0].date == "2026-10-06"
    assert pai[0].daily_pai == 12.5
    assert pai[0].total_pai == 80
    assert pai[0].low_zone_pai == 4
    assert pai[0].high_zone_pai == 3

    hours = await _collect(adapter.iter_stand_hours("2026-10-06", "2026-10-06"))
    assert len(hours) == 1
    assert hours[0].start_at == datetime.fromtimestamp(DAY, TZ8)
    assert hours[0].end_at - hours[0].start_at == timedelta(hours=1)
    daily = await _collect(adapter.iter_stand_daily("2026-10-06", "2026-10-06"))
    assert daily[0].date == "2026-10-06"
    assert daily[0].stand_hours == 8

    events = await _collect(adapter.iter_menstruation("2026-10-01", "2026-10-08"))
    assert [(event.status, event.event_date) for event in events] == [
        (1, "2026-10-06"),
        (3, "2026-10-07"),
    ]
    assert events[0].update_time == datetime.fromtimestamp(DAY + 60, TZ8)

    loads = await _collect(adapter.iter_training_load("2026-10-06", "2026-10-06"))
    assert loads[0].current_day_train_load == 40
    assert loads[0].wtl_sum == 210
    assert loads[0].wtl_sum_optimal_min == 150
    assert loads[0].wtl_sum_optimal_max == 300
    assert loads[0].wtl_sum_overreaching == 450

    samples = await _collect(adapter.iter_intensity("2026-10-06", "2026-10-06"))
    assert [sample.timestamp for sample in samples] == [
        datetime.fromtimestamp(DAY, TZ8),
        datetime.fromtimestamp(DAY + 1800, TZ8),
    ]
    intensity_daily = await _collect(adapter.iter_intensity_daily("2026-10-06", "2026-10-06"))
    assert intensity_daily[0].duration_minutes == 46


@pytest.mark.asyncio
async def test_sleep_score_filled_from_daily_report(monkeypatch):
    adapter = _adapter()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "watch_night_sleep":
            return [
                _item(
                    {
                        "bedtime": DAY - 5 * 3600,
                        "wake_up_time": DAY + 300,
                        "duration": 305,
                        "sleep_awake_duration": 0,
                    }
                ),
                _item(
                    {
                        "bedtime": DAY + 8 * 3600,
                        "wake_up_time": DAY + 9 * 3600,
                        "duration": 60,
                        "is_nap": True,
                    },
                    time=DAY + 9 * 3600,
                ),
            ]
        if key == "sleep":
            return [
                _item(
                    {
                        "bedtime": DAY - 4 * 3600,
                        "wake_up_time": DAY + 600,
                        "duration": 280,
                        "score": 80,
                    },
                    time=DAY + 600,
                )
            ]
        return []

    async def fake_aggregated(key, start_date, end_date, tag="daily_report", region=None):
        assert key == "sleep"
        return [_item({"sleep_score": 55, "segment_details": []})]

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    monkeypatch.setattr(adapter, "_fetch_aggregated", fake_aggregated)
    sessions = await _collect(adapter.iter_sleep_sessions("2026-10-06", "2026-10-06"))

    by_duration = {session.duration_minutes: session.sleep_score for session in sessions}
    assert by_duration[305] == 55
    assert by_duration[280] == 80
    assert by_duration[60] is None


@pytest.mark.asyncio
async def test_sleep_score_keeps_sessions_when_report_fails(monkeypatch):
    adapter = _adapter()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "sleep":
            return [
                _item(
                    {
                        "bedtime": DAY - 5 * 3600,
                        "wake_up_time": DAY + 300,
                        "duration": 305,
                    }
                )
            ]
        return []

    async def broken_aggregated(*args, **kwargs):
        raise RuntimeError("cloud unavailable")

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    monkeypatch.setattr(adapter, "_fetch_aggregated", broken_aggregated)
    sessions = await _collect(adapter.iter_sleep_sessions("2026-10-06", "2026-10-06"))
    assert len(sessions) == 1
    assert sessions[0].sleep_score is None


@pytest.mark.asyncio
async def test_sync_and_query_roundtrip(tmp_path, monkeypatch):
    adapter = _adapter()

    async def fake_fetch(key, start_date, end_date, region=None):
        if key == "pai":
            return [
                _item(
                    {
                        "date_time": DAY,
                        "daily_pai": 7,
                        "total_pai": 30,
                        "low_zone_pai": 1,
                        "medium_zone_pai": 2,
                        "high_zone_pai": 4,
                    }
                )
            ]
        if key == "valid_stand":
            return [_item({"start_time": DAY, "end_time": DAY + 3600})]
        if key == "menstruation":
            return [_item({"status": 2, "date_time": DAY})]
        if key == "training_load":
            return [_item({"date_time": DAY, "current_day_train_load": 15, "wtl_sum": 90})]
        if key == "intensity":
            return [_item({"time": DAY})]
        return []

    async def fake_aggregated(key, start_date, end_date, tag="daily_report", region=None):
        if key == "valid_stand":
            return [_item({"count": 6})]
        if key == "intensity":
            return [_item({"duration": 22})]
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fake_fetch)
    monkeypatch.setattr(adapter, "_fetch_aggregated", fake_aggregated)
    db = Database(tmp_path / "extra.db")
    service = SyncService(adapter, db, chunk_days=7)
    for data_type in ("pai", "valid_stand", "menstruation", "training_load", "intensity"):
        result = await service.sync_data_type(data_type, "2026-10-06", "2026-10-06")
        assert result["status"] == "ok"
        assert result["added"] >= 1

    query = QueryService(db, "u1")
    assert query.get_pai_daily("2026-10-06", "2026-10-06")[0]["daily_pai"] == 7
    stand = query.get_valid_stand("2026-10-06", "2026-10-06")
    assert len(stand["hours"]) == 1
    assert stand["daily"][0]["stand_hours"] == 6
    period = query.get_menstruation_events("2026-10-06", "2026-10-06")
    assert period[0]["status"] == 2
    assert period[0]["status_label"] == "end"
    assert query.get_training_load("2026-10-06", "2026-10-06")[0]["wtl_sum"] == 90
    intensity = query.get_intensity("2026-10-06", "2026-10-06")
    assert len(intensity["samples"]) == 1
    assert intensity["daily"][0]["duration_minutes"] == 22

    coverage = {row["data_type"] for row in query.get_data_coverage(None)}
    assert {"pai", "valid_stand", "menstruation", "training_load", "intensity"} <= coverage
