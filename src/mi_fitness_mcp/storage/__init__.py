"""SQLite storage layer for Mi Fitness MCP."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from mi_fitness_mcp.models import (
    AbnormalHeartBeatEvent,
    BodyMeasurement,
    DailyActivity,
    HeartRateSample,
    IntensityDaily,
    IntensitySample,
    MenstruationEvent,
    PaiDaily,
    SleepSession,
    SpO2Sample,
    StandDaily,
    StandHour,
    StressSample,
    TrainingLoadDaily,
    Workout,
)


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: Path | str):
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            # 日常活动表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date TEXT NOT NULL,
                    steps INTEGER NOT NULL DEFAULT 0,
                    distance_m REAL NOT NULL DEFAULT 0,
                    active_kcal REAL NOT NULL DEFAULT 0,
                    total_kcal REAL,
                    floors INTEGER,
                    active_minutes INTEGER,
                    UNIQUE(user_id, date, device_id)
                )
            """)

            # 睡眠记录表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sleep_sessions (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sleep_id TEXT NOT NULL,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    time_asleep_minutes INTEGER NOT NULL,
                    time_awake_minutes INTEGER NOT NULL,
                    sleep_score INTEGER,
                    is_nap BOOLEAN DEFAULT FALSE,
                    stages TEXT,  -- JSON array of sleep stages
                    UNIQUE(user_id, sleep_id)
                )
            """)

            # 运动记录表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workouts (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    workout_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    distance_m REAL,
                    calories_kcal REAL,
                    avg_heart_rate_bpm INTEGER,
                    max_heart_rate_bpm INTEGER,
                    avg_pace_sec_per_km REAL,
                    max_pace_sec_per_km REAL,
                    total_steps INTEGER,
                    UNIQUE(user_id, workout_id)
                )
            """)

            # 身体测量表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS body_measurements (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timestamp TIMESTAMP NOT NULL,
                    weight_kg REAL NOT NULL,
                    bmi REAL,
                    body_fat_pct REAL,
                    muscle_mass_kg REAL,
                    water_pct REAL,
                    bone_mass_kg REAL,
                    visceral_fat_score INTEGER,
                    basal_metabolism_kcal INTEGER,
                    metabolic_age INTEGER,
                    UNIQUE(user_id, timestamp, device_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS heart_rate_samples (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timestamp TIMESTAMP NOT NULL,
                    bpm INTEGER NOT NULL,
                    sample_type TEXT NOT NULL,
                    UNIQUE(user_id, timestamp, sample_type)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS spo2_samples (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timestamp TIMESTAMP NOT NULL,
                    spo2_pct INTEGER NOT NULL,
                    UNIQUE(user_id, timestamp)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS stress_samples (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timestamp TIMESTAMP NOT NULL,
                    stress_score INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    UNIQUE(user_id, timestamp)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS abnormal_heart_beat_events (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_id TEXT NOT NULL,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    UNIQUE(user_id, event_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pai_daily (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date TEXT NOT NULL,
                    daily_pai REAL NOT NULL DEFAULT 0,
                    total_pai REAL NOT NULL DEFAULT 0,
                    low_zone_pai REAL NOT NULL DEFAULT 0,
                    medium_zone_pai REAL NOT NULL DEFAULT 0,
                    high_zone_pai REAL NOT NULL DEFAULT 0,
                    UNIQUE(user_id, date)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS stand_hours (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    UNIQUE(user_id, start_at)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS stand_daily (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date TEXT NOT NULL,
                    stand_hours INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, date)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS menstruation_events (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_date TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    date_time TIMESTAMP NOT NULL,
                    update_time TIMESTAMP,
                    UNIQUE(user_id, date_time, status)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS training_load_daily (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date TEXT NOT NULL,
                    current_day_train_load REAL,
                    wtl_sum REAL,
                    wtl_sum_optimal_min REAL,
                    wtl_sum_optimal_max REAL,
                    wtl_sum_overreaching REAL,
                    UNIQUE(user_id, date)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS intensity_samples (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    timestamp TIMESTAMP NOT NULL,
                    UNIQUE(user_id, timestamp)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS intensity_daily (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_record_id TEXT,
                    user_id TEXT NOT NULL,
                    device_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    collected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, date)
                )
            """)

            # 同步状态表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_type TEXT NOT NULL UNIQUE,
                    last_sync_at TIMESTAMP,
                    last_record_timestamp TIMESTAMP,
                    records_count INTEGER DEFAULT 0
                )
            """)

            # 创建索引以提升查询性能
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_user_date
                ON daily_activity(user_id, date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sleep_user_start
                ON sleep_sessions(user_id, start_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workouts_user_start
                ON workouts(user_id, start_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_measurements_user_ts
                ON body_measurements(user_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_heart_rate_user_ts
                ON heart_rate_samples(user_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_spo2_user_ts
                ON spo2_samples(user_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stress_user_ts
                ON stress_samples(user_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_abnormal_hr_user_start
                ON abnormal_heart_beat_events(user_id, start_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pai_user_date
                ON pai_daily(user_id, date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stand_hours_user_start
                ON stand_hours(user_id, start_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stand_daily_user_date
                ON stand_daily(user_id, date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_menstruation_user_date
                ON menstruation_events(user_id, event_date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_training_load_user_date
                ON training_load_daily(user_id, date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_intensity_user_ts
                ON intensity_samples(user_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_intensity_daily_user_date
                ON intensity_daily(user_id, date)
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def insert_daily_activity(self, activity: DailyActivity) -> bool:
        """Insert or update daily activity record.

        Returns:
            True if record was inserted, False if updated
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO daily_activity (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, date, steps, distance_m, active_kcal,
                    total_kcal, floors, active_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    steps = excluded.steps,
                    distance_m = excluded.distance_m,
                    active_kcal = excluded.active_kcal,
                    total_kcal = excluded.total_kcal,
                    floors = excluded.floors,
                    active_minutes = excluded.active_minutes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    activity.id,
                    activity.provider,
                    activity.source_type,
                    activity.source_record_id,
                    activity.user_id,
                    activity.device_id,
                    activity.timezone,
                    activity.collected_at.isoformat() if activity.collected_at else None,
                    activity.date,
                    activity.steps,
                    activity.distance_m,
                    activity.active_kcal,
                    activity.total_kcal,
                    activity.floors,
                    activity.active_minutes,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_sleep_session(self, sleep: SleepSession) -> bool:
        """Insert or update sleep session record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sleep_sessions (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, sleep_id, start_at, end_at, duration_minutes,
                    time_asleep_minutes, time_awake_minutes, sleep_score, is_nap, stages
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, sleep_id) DO UPDATE SET
                    duration_minutes = excluded.duration_minutes,
                    time_asleep_minutes = excluded.time_asleep_minutes,
                    time_awake_minutes = excluded.time_awake_minutes,
                    sleep_score = excluded.sleep_score,
                    stages = excluded.stages,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sleep.id,
                    sleep.provider,
                    sleep.source_type,
                    sleep.source_record_id,
                    sleep.user_id,
                    sleep.device_id,
                    sleep.timezone,
                    sleep.collected_at.isoformat() if sleep.collected_at else None,
                    sleep.sleep_id,
                    sleep.start_at.isoformat(),
                    sleep.end_at.isoformat(),
                    sleep.duration_minutes,
                    sleep.time_asleep_minutes,
                    sleep.time_awake_minutes,
                    sleep.sleep_score,
                    sleep.is_nap,
                    json.dumps([s.model_dump() for s in sleep.stages]),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_workout(self, workout: Workout) -> bool:
        """Insert or update workout record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workouts (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, workout_id, activity_type, start_at, end_at,
                    duration_minutes, distance_m, calories_kcal, avg_heart_rate_bpm,
                    max_heart_rate_bpm, avg_pace_sec_per_km, max_pace_sec_per_km, total_steps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, workout_id) DO UPDATE SET
                    duration_minutes = excluded.duration_minutes,
                    distance_m = excluded.distance_m,
                    calories_kcal = excluded.calories_kcal,
                    avg_heart_rate_bpm = excluded.avg_heart_rate_bpm,
                    max_heart_rate_bpm = excluded.max_heart_rate_bpm,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    workout.id,
                    workout.provider,
                    workout.source_type,
                    workout.source_record_id,
                    workout.user_id,
                    workout.device_id,
                    workout.timezone,
                    workout.collected_at.isoformat() if workout.collected_at else None,
                    workout.workout_id,
                    workout.activity_type,
                    workout.start_at.isoformat(),
                    workout.end_at.isoformat(),
                    workout.duration_minutes,
                    workout.distance_m,
                    workout.calories_kcal,
                    workout.avg_heart_rate_bpm,
                    workout.max_heart_rate_bpm,
                    workout.avg_pace_sec_per_km,
                    workout.max_pace_sec_per_km,
                    workout.total_steps,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_body_measurement(self, measurement: BodyMeasurement) -> bool:
        """Insert or update body measurement record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO body_measurements (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, timestamp, weight_kg, bmi, body_fat_pct,
                    muscle_mass_kg, water_pct, bone_mass_kg, visceral_fat_score,
                    basal_metabolism_kcal, metabolic_age
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    weight_kg = excluded.weight_kg,
                    bmi = excluded.bmi,
                    body_fat_pct = excluded.body_fat_pct,
                    muscle_mass_kg = excluded.muscle_mass_kg,
                    water_pct = excluded.water_pct,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    measurement.id,
                    measurement.provider,
                    measurement.source_type,
                    measurement.source_record_id,
                    measurement.user_id,
                    measurement.device_id,
                    measurement.timezone,
                    measurement.collected_at.isoformat() if measurement.collected_at else None,
                    measurement.timestamp.isoformat(),
                    measurement.weight_kg,
                    measurement.bmi,
                    measurement.body_fat_pct,
                    measurement.muscle_mass_kg,
                    measurement.water_pct,
                    measurement.bone_mass_kg,
                    measurement.visceral_fat_score,
                    measurement.basal_metabolism_kcal,
                    measurement.metabolic_age,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_heart_rate_sample(self, sample: HeartRateSample) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO heart_rate_samples (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, timestamp, bpm, sample_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    timestamp = excluded.timestamp,
                    bpm = excluded.bpm,
                    sample_type = excluded.sample_type,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sample.id,
                    sample.provider,
                    sample.source_type,
                    sample.source_record_id,
                    sample.user_id,
                    sample.device_id,
                    sample.timezone,
                    sample.collected_at.isoformat() if sample.collected_at else None,
                    sample.timestamp.isoformat(),
                    sample.bpm,
                    sample.sample_type,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_spo2_sample(self, sample: SpO2Sample) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO spo2_samples (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, timestamp, spo2_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    timestamp = excluded.timestamp,
                    spo2_pct = excluded.spo2_pct,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sample.id,
                    sample.provider,
                    sample.source_type,
                    sample.source_record_id,
                    sample.user_id,
                    sample.device_id,
                    sample.timezone,
                    sample.collected_at.isoformat() if sample.collected_at else None,
                    sample.timestamp.isoformat(),
                    sample.spo2_pct,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_stress_sample(self, sample: StressSample) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stress_samples (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, timestamp, stress_score, level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    timestamp = excluded.timestamp,
                    stress_score = excluded.stress_score,
                    level = excluded.level,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    sample.id,
                    sample.provider,
                    sample.source_type,
                    sample.source_record_id,
                    sample.user_id,
                    sample.device_id,
                    sample.timezone,
                    sample.collected_at.isoformat() if sample.collected_at else None,
                    sample.timestamp.isoformat(),
                    sample.stress_score,
                    sample.level,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_abnormal_heart_beat_event(self, event: AbnormalHeartBeatEvent) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO abnormal_heart_beat_events (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, event_id, start_at, end_at, duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, event_id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    start_at = excluded.start_at,
                    end_at = excluded.end_at,
                    duration_seconds = excluded.duration_seconds,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    event.id,
                    event.provider,
                    event.source_type,
                    event.source_record_id,
                    event.user_id,
                    event.device_id,
                    event.timezone,
                    event.collected_at.isoformat() if event.collected_at else None,
                    event.event_id,
                    event.start_at.isoformat(),
                    event.end_at.isoformat(),
                    event.duration_seconds,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def _stamp(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    def insert_pai_daily(self, record: PaiDaily) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pai_daily (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, date, daily_pai, total_pai,
                    low_zone_pai, medium_zone_pai, high_zone_pai
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    daily_pai = excluded.daily_pai,
                    total_pai = excluded.total_pai,
                    low_zone_pai = excluded.low_zone_pai,
                    medium_zone_pai = excluded.medium_zone_pai,
                    high_zone_pai = excluded.high_zone_pai,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.date,
                    record.daily_pai,
                    record.total_pai,
                    record.low_zone_pai,
                    record.medium_zone_pai,
                    record.high_zone_pai,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_stand_hour(self, record: StandHour) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stand_hours (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, start_at, end_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    start_at = excluded.start_at,
                    end_at = excluded.end_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.start_at.isoformat(),
                    record.end_at.isoformat(),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_stand_daily(self, record: StandDaily) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stand_daily (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, date, stand_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    stand_hours = excluded.stand_hours,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.date,
                    record.stand_hours,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_menstruation_event(self, record: MenstruationEvent) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO menstruation_events (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, event_date, status, date_time, update_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    event_date = excluded.event_date,
                    status = excluded.status,
                    date_time = excluded.date_time,
                    update_time = excluded.update_time,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.event_date,
                    record.status,
                    record.date_time.isoformat(),
                    self._stamp(record.update_time),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_training_load_daily(self, record: TrainingLoadDaily) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO training_load_daily (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, date, current_day_train_load, wtl_sum,
                    wtl_sum_optimal_min, wtl_sum_optimal_max, wtl_sum_overreaching
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    current_day_train_load = excluded.current_day_train_load,
                    wtl_sum = excluded.wtl_sum,
                    wtl_sum_optimal_min = excluded.wtl_sum_optimal_min,
                    wtl_sum_optimal_max = excluded.wtl_sum_optimal_max,
                    wtl_sum_overreaching = excluded.wtl_sum_overreaching,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.date,
                    record.current_day_train_load,
                    record.wtl_sum,
                    record.wtl_sum_optimal_min,
                    record.wtl_sum_optimal_max,
                    record.wtl_sum_overreaching,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_intensity_sample(self, record: IntensitySample) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO intensity_samples (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    timestamp = excluded.timestamp,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.timestamp.isoformat(),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def insert_intensity_daily(self, record: IntensityDaily) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO intensity_daily (
                    id, provider, source_type, source_record_id, user_id, device_id,
                    timezone, collected_at, date, duration_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timezone = excluded.timezone,
                    collected_at = excluded.collected_at,
                    duration_minutes = excluded.duration_minutes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.id,
                    record.provider,
                    record.source_type,
                    record.source_record_id,
                    record.user_id,
                    record.device_id,
                    record.timezone,
                    self._stamp(record.collected_at),
                    record.date,
                    record.duration_minutes,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_sync_state(self, data_type: str, last_record_ts: datetime | None = None) -> None:
        """Update sync state for a data type."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (data_type, last_sync_at, last_record_timestamp)
                VALUES (?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(data_type) DO UPDATE SET
                    last_sync_at = CURRENT_TIMESTAMP,
                    last_record_timestamp = excluded.last_record_timestamp
                """,
                (data_type, last_record_ts.isoformat() if last_record_ts else None),
            )
            conn.commit()

    def get_sync_state(self, data_type: str) -> dict[str, Any] | None:
        """Get sync state for a data type."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE data_type = ?",
                (data_type,),
            ).fetchone()
            return dict(row) if row else None

    def query_daily_activity(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Query daily activity records."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM daily_activity
                WHERE user_id = ? AND date >= ? AND date <= ?
                ORDER BY date
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_sleep_sessions(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Query sleep session records."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sleep_sessions
                WHERE user_id = ?
                AND substr(start_at, 1, 10) >= ? AND substr(start_at, 1, 10) <= ?
                ORDER BY start_at
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_workouts(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Query workout records."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workouts
                WHERE user_id = ?
                AND substr(start_at, 1, 10) >= ? AND substr(start_at, 1, 10) <= ?
                ORDER BY start_at
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_body_measurements(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Query body measurement records."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM body_measurements
                WHERE user_id = ?
                AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
                ORDER BY timestamp
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_heart_rate_samples(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM heart_rate_samples
                WHERE user_id = ?
                AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
                ORDER BY timestamp
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_spo2_samples(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM spo2_samples
                WHERE user_id = ?
                AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
                ORDER BY timestamp
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_stress_samples(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM stress_samples
                WHERE user_id = ?
                AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
                ORDER BY timestamp
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_abnormal_heart_beat_events(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM abnormal_heart_beat_events
                WHERE user_id = ?
                AND substr(start_at, 1, 10) >= ? AND substr(start_at, 1, 10) <= ?
                ORDER BY start_at
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def _query_by_date_column(
        self,
        table: str,
        user_id: str,
        start_date: str,
        end_date: str,
        column: str = "date",
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {table}
                WHERE user_id = ? AND {column} >= ? AND {column} <= ?
                ORDER BY {column}
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_pai_daily(self, user_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self._query_by_date_column("pai_daily", user_id, start_date, end_date)

    def query_stand_hours(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM stand_hours
                WHERE user_id = ?
                AND substr(start_at, 1, 10) >= ? AND substr(start_at, 1, 10) <= ?
                ORDER BY start_at
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_stand_daily(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return self._query_by_date_column("stand_daily", user_id, start_date, end_date)

    def query_menstruation_events(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return self._query_by_date_column(
            "menstruation_events", user_id, start_date, end_date, column="event_date"
        )

    def query_training_load_daily(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return self._query_by_date_column("training_load_daily", user_id, start_date, end_date)

    def query_intensity_samples(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM intensity_samples
                WHERE user_id = ?
                AND substr(timestamp, 1, 10) >= ? AND substr(timestamp, 1, 10) <= ?
                ORDER BY timestamp
                """,
                (user_id, start_date, end_date),
            ).fetchall()
            return [dict(row) for row in rows]

    def query_intensity_daily(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return self._query_by_date_column("intensity_daily", user_id, start_date, end_date)

    def get_data_coverage(self, user_id: str) -> list[dict[str, Any]]:
        """Get data coverage statistics."""
        with self._get_connection() as conn:
            results = []

            # 日常活动覆盖范围
            row = conn.execute(
                """
                SELECT
                    MIN(date) as first_date,
                    MAX(date) as last_date,
                    COUNT(DISTINCT date) as days_with_data
                FROM daily_activity
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row and row["first_date"]:
                results.append(
                    {
                        "data_type": "daily_activity",
                        **dict(row),
                    }
                )

            # 睡眠覆盖范围
            row = conn.execute(
                """
                SELECT
                    MIN(substr(start_at, 1, 10)) as first_date,
                    MAX(substr(start_at, 1, 10)) as last_date,
                    COUNT(DISTINCT substr(start_at, 1, 10)) as days_with_data
                FROM sleep_sessions
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row and row["first_date"]:
                results.append(
                    {
                        "data_type": "sleep",
                        **dict(row),
                    }
                )

            # 运动记录覆盖范围
            row = conn.execute(
                """
                SELECT
                    MIN(substr(start_at, 1, 10)) as first_date,
                    MAX(substr(start_at, 1, 10)) as last_date,
                    COUNT(DISTINCT substr(start_at, 1, 10)) as days_with_data
                FROM workouts
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row and row["first_date"]:
                results.append(
                    {
                        "data_type": "workouts",
                        **dict(row),
                    }
                )

            # 身体测量覆盖范围
            row = conn.execute(
                """
                SELECT
                    MIN(substr(timestamp, 1, 10)) as first_date,
                    MAX(substr(timestamp, 1, 10)) as last_date,
                    COUNT(DISTINCT substr(timestamp, 1, 10)) as days_with_data
                FROM body_measurements
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row and row["first_date"]:
                results.append(
                    {
                        "data_type": "body_measurements",
                        **dict(row),
                    }
                )

            row = conn.execute(
                """
                SELECT
                    MIN(substr(timestamp, 1, 10)) as first_date,
                    MAX(substr(timestamp, 1, 10)) as last_date,
                    COUNT(DISTINCT substr(timestamp, 1, 10)) as days_with_data
                FROM heart_rate_samples
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row and row["first_date"]:
                results.append(
                    {
                        "data_type": "heart_rate",
                        **dict(row),
                    }
                )

            for data_type, table_name, date_expr in [
                ("spo2", "spo2_samples", "timestamp"),
                ("stress", "stress_samples", "timestamp"),
                ("abnormal_heart_beat", "abnormal_heart_beat_events", "start_at"),
                ("pai", "pai_daily", "date"),
                ("menstruation", "menstruation_events", "event_date"),
                ("training_load", "training_load_daily", "date"),
            ]:
                row = conn.execute(
                    f"""
                    SELECT
                        MIN(date({date_expr})) as first_date,
                        MAX(date({date_expr})) as last_date,
                        COUNT(DISTINCT date({date_expr})) as days_with_data
                    FROM {table_name}
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if row and row["first_date"]:
                    results.append({"data_type": data_type, **dict(row)})

            for data_type, sql in [
                (
                    "valid_stand",
                    """
                    SELECT substr(start_at, 1, 10) AS d FROM stand_hours WHERE user_id = ?
                    UNION
                    SELECT date AS d FROM stand_daily WHERE user_id = ?
                    """,
                ),
                (
                    "intensity",
                    """
                    SELECT substr(timestamp, 1, 10) AS d FROM intensity_samples WHERE user_id = ?
                    UNION
                    SELECT date AS d FROM intensity_daily WHERE user_id = ?
                    """,
                ),
            ]:
                row = conn.execute(
                    f"""
                    SELECT
                        MIN(d) AS first_date,
                        MAX(d) AS last_date,
                        COUNT(*) AS days_with_data
                    FROM ({sql})
                    """,
                    (user_id, user_id),
                ).fetchone()
                if row and row["first_date"]:
                    results.append({"data_type": data_type, **dict(row)})

            return results
