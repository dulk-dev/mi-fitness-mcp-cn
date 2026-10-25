import json
from datetime import datetime

from mi_fitness_mcp.models import (
    BodyMeasurement,
    DailyActivity,
    HeartRateSample,
    SleepSession,
    SleepStage,
)
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database


def test_storage_and_query_roundtrip(tmp_path):
    db = Database(tmp_path / "test.db")

    activity = DailyActivity(
        id="a1",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u1",
        date="2025-04-01",
        steps=1000,
        distance_m=800,
        active_kcal=50,
    )
    hr = HeartRateSample(
        id="hr1",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u1",
        timestamp=datetime(2025, 4, 1, 12, 0, 0),
        bpm=70,
        sample_type="passive",
    )
    body = BodyMeasurement(
        id="w1",
        provider="mi_fitness",
        source_type="cloud_session",
        user_id="u1",
        timestamp=datetime(2025, 4, 1, 7, 0, 0),
        weight_kg=101.5,
        bmi=28.0,
    )

    db.insert_daily_activity(activity)
    db.insert_heart_rate_sample(hr)
    db.insert_body_measurement(body)

    query = QueryService(db, "u1")
    assert len(query.get_daily_summaries("2025-04-01", "2025-04-01")) == 1
    assert len(query.get_heart_rate_samples("2025-04-01", "2025-04-01")) == 1
    assert len(query.get_body_measurements("2025-04-01", "2025-04-01")) == 1


def test_sleep_session_upsert_overwrites_finalized_window(tmp_path):
    """A later sync of the same (user_id, sleep_id) replaces the partial night."""
    db = Database(tmp_path / "test.db")
    partial = SleepSession(
        id="sleep-partial",
        provider="mi_fitness",
        source_type="cloud_session",
        source_record_id="morning-partial",
        user_id="u1",
        device_id="band-1",
        timezone="Asia/Shanghai",
        collected_at=datetime(2026, 10, 25, 5, 30),
        sleep_id="sid-night",
        start_at=datetime(2026, 10, 25, 0, 10),
        end_at=datetime(2026, 10, 25, 5, 22),
        duration_minutes=264,
        time_asleep_minutes=240,
        time_awake_minutes=24,
        sleep_score=60,
        is_nap=True,
        stages=[SleepStage(stage="light", minutes=240)],
    )
    finalized = SleepSession(
        id="sleep-finalized",
        provider="mi_fitness",
        source_type="cloud_session",
        source_record_id="finalized",
        user_id="u1",
        device_id="band-2",
        timezone="Asia/Shanghai",
        collected_at=datetime(2026, 10, 25, 8, 5),
        sleep_id="sid-night",
        start_at=datetime(2026, 10, 25, 0, 58),
        end_at=datetime(2026, 10, 25, 7, 58),
        duration_minutes=410,
        time_asleep_minutes=390,
        time_awake_minutes=20,
        sleep_score=82,
        is_nap=False,
        stages=[
            SleepStage(stage="deep", minutes=120),
            SleepStage(stage="light", minutes=200),
            SleepStage(stage="rem", minutes=70),
        ],
    )

    assert db.insert_sleep_session(partial)
    assert db.insert_sleep_session(finalized)

    rows = db.query_sleep_sessions("u1", "2026-10-25", "2026-10-25")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "sleep-partial"
    assert row["start_at"] == "2026-10-25T00:58:00"
    assert row["end_at"] == "2026-10-25T07:58:00"
    assert row["duration_minutes"] == 410
    assert row["time_asleep_minutes"] == 390
    assert row["time_awake_minutes"] == 20
    assert row["sleep_score"] == 82
    assert row["source_record_id"] == "finalized"
    assert row["device_id"] == "band-2"
    assert row["collected_at"] == "2026-10-25T08:05:00"
    assert row["is_nap"] in (0, False)
    assert json.loads(row["stages"]) == [
        {"stage": "deep", "minutes": 120},
        {"stage": "light", "minutes": 200},
        {"stage": "rem", "minutes": 70},
    ]
