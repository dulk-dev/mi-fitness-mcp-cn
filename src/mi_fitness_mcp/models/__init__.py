"""Pydantic models for Mi Fitness MCP."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BaseEntity(BaseModel):
    """Base entity with common fields."""

    id: str = Field(description="Internal UUID")
    provider: Literal["mi_fitness"] = Field(description="Data provider")
    source_type: Literal["cloud_session"] = Field(description="Source of the data")
    source_record_id: str | None = Field(None, description="Provider's native ID")
    user_id: str = Field(description="User identifier")
    device_id: str | None = Field(None, description="Device that recorded the data")
    timezone: str = Field(default="UTC", description="Timezone for the data")
    collected_at: datetime | None = Field(None, description="When data was recorded")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class DailyActivity(BaseEntity):
    """Daily activity summary (steps, calories, etc.)."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    steps: int = Field(ge=0, description="Number of steps")
    distance_m: float = Field(ge=0, description="Distance in meters")
    active_kcal: float = Field(ge=0, description="Active calories burned")
    total_kcal: float | None = Field(None, ge=0, description="Total calories")
    floors: int | None = Field(None, ge=0, description="Floors climbed")
    active_minutes: int | None = Field(None, ge=0, description="Active minutes")


class SleepStage(BaseModel):
    """Sleep stage information."""

    stage: Literal["deep", "light", "rem", "awake"] = Field(description="Sleep stage")
    minutes: int = Field(ge=0, description="Duration in minutes")


class SleepSession(BaseEntity):
    """Sleep session data."""

    sleep_id: str = Field(description="Unique sleep session ID")
    start_at: datetime = Field(description="Sleep start time")
    end_at: datetime = Field(description="Sleep end time")
    duration_minutes: int = Field(ge=0, description="Total duration")
    time_asleep_minutes: int = Field(ge=0, description="Actual sleep time")
    time_awake_minutes: int = Field(ge=0, description="Time awake during sleep")
    sleep_score: int | None = Field(None, ge=0, le=100, description="Sleep quality score")
    is_nap: bool = Field(default=False, description="Whether this is a nap")
    stages: list[SleepStage] = Field(default_factory=list, description="Sleep stages breakdown")


class Workout(BaseEntity):
    """Workout/exercise session."""

    workout_id: str = Field(description="Unique workout ID")
    activity_type: str = Field(description="Type of activity (running, cycling, etc.)")
    start_at: datetime = Field(description="Workout start time")
    end_at: datetime = Field(description="Workout end time")
    duration_minutes: int = Field(ge=0, description="Duration in minutes")
    distance_m: float | None = Field(None, ge=0, description="Distance in meters")
    calories_kcal: float | None = Field(None, ge=0, description="Calories burned")
    avg_heart_rate_bpm: int | None = Field(None, ge=0, description="Average heart rate")
    max_heart_rate_bpm: int | None = Field(None, ge=0, description="Maximum heart rate")
    avg_pace_sec_per_km: float | None = Field(None, ge=0, description="Average pace")
    max_pace_sec_per_km: float | None = Field(None, ge=0, description="Maximum pace")
    total_steps: int | None = Field(None, ge=0, description="Steps during workout")


class BodyMeasurement(BaseEntity):
    """Body composition measurement (from smart scale)."""

    timestamp: datetime = Field(description="Measurement time")
    weight_kg: float = Field(gt=0, description="Weight in kilograms")
    bmi: float | None = Field(None, gt=0, description="Body mass index")
    body_fat_pct: float | None = Field(None, ge=0, le=100, description="Body fat percentage")
    muscle_mass_kg: float | None = Field(None, ge=0, description="Muscle mass")
    water_pct: float | None = Field(None, ge=0, le=100, description="Body water percentage")
    bone_mass_kg: float | None = Field(None, ge=0, description="Bone mass")
    visceral_fat_score: int | None = Field(None, ge=0, description="Visceral fat level")
    basal_metabolism_kcal: int | None = Field(None, ge=0, description="BMR in kcal")
    metabolic_age: int | None = Field(None, ge=0, description="Metabolic age")


class HeartRateSample(BaseEntity):
    """Heart rate measurement."""

    timestamp: datetime = Field(description="Measurement time")
    bpm: int = Field(ge=0, description="Heart rate in beats per minute")
    sample_type: Literal["resting", "active", "passive", "workout"] = Field(
        default="passive", description="Type of measurement"
    )


class SpO2Sample(BaseEntity):
    """Blood oxygen saturation measurement."""

    timestamp: datetime = Field(description="Measurement time")
    spo2_pct: int = Field(ge=0, le=100, description="SpO2 percentage")


class StressSample(BaseEntity):
    """Stress level measurement."""

    timestamp: datetime = Field(description="Measurement time")
    stress_score: int = Field(ge=0, le=100, description="Stress score")
    level: Literal["low", "medium", "high"] = Field(description="Stress level category")


class AbnormalHeartBeatEvent(BaseEntity):
    """Abnormal heart beat event."""

    event_id: str = Field(description="Unique abnormal heart beat event ID")
    start_at: datetime = Field(description="Event start time")
    end_at: datetime = Field(description="Event end time")
    duration_seconds: int = Field(ge=0, description="Event duration in seconds")


class PaiDaily(BaseEntity):
    """Daily PAI (personal activity intelligence) summary. Cloud key: pai."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    daily_pai: float = Field(ge=0, description="PAI earned that day")
    total_pai: float = Field(ge=0, description="Rolling total PAI")
    low_zone_pai: float = Field(ge=0, description="Low heart-rate zone PAI")
    medium_zone_pai: float = Field(ge=0, description="Medium heart-rate zone PAI")
    high_zone_pai: float = Field(ge=0, description="High heart-rate zone PAI")


class StandHour(BaseEntity):
    """One hour credited as standing. Cloud key: valid_stand."""

    start_at: datetime = Field(description="Hour start")
    end_at: datetime = Field(description="Hour end")


class StandDaily(BaseEntity):
    """Daily standing-hour count from the aggregated daily report."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    stand_hours: int = Field(ge=0, description="Valid standing hours, daily report count")


class MenstruationEvent(BaseEntity):
    """Period start/end marker. Cloud key: menstruation. status 1=start, 2=end, 3=both."""

    event_date: str = Field(description="Calendar date in YYYY-MM-DD format")
    status: int = Field(ge=1, le=3, description="1=start, 2=end, 3=both")
    date_time: datetime = Field(description="Marker time from the cloud record")
    update_time: datetime | None = Field(None, description="When the marker was last edited")


class TrainingLoadDaily(BaseEntity):
    """Daily training load. Cloud key: training_load."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    current_day_train_load: float | None = Field(None, ge=0, description="Load for that day")
    wtl_sum: float | None = Field(None, ge=0, description="Weekly training load sum")
    wtl_sum_optimal_min: float | None = Field(
        None, ge=0, description="Optimal weekly load lower bound"
    )
    wtl_sum_optimal_max: float | None = Field(
        None, ge=0, description="Optimal weekly load upper bound"
    )
    wtl_sum_overreaching: float | None = Field(
        None, ge=0, description="Overreaching weekly load threshold"
    )


class IntensitySample(BaseEntity):
    """Moderate-to-vigorous intensity sample. Cloud key: intensity, payload time."""

    timestamp: datetime = Field(description="Sample time")


class IntensityDaily(BaseEntity):
    """Daily moderate-to-vigorous minutes from the aggregated daily report."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    duration_minutes: int = Field(ge=0, description="Intensity duration in minutes")


class UserProfile(BaseModel):
    """User profile information."""

    user_id: str = Field(description="User identifier")
    display_name: str | None = Field(None, description="Display name")
    birth_year: int | None = Field(None, description="Birth year")
    sex: Literal["male", "female", "other"] | None = Field(None, description="Sex")
    height_cm: float | None = Field(None, gt=0, description="Height in cm")
    timezone: str = Field(default="UTC", description="User timezone")
    devices: list[dict[str, Any]] = Field(default_factory=list, description="Connected devices")


class DeviceInfo(BaseModel):
    """Connected device information."""

    device_id: str = Field(description="Device identifier")
    device_type: str = Field(description="Type (band, watch, scale)")
    model: str = Field(description="Device model")
    firmware_version: str | None = Field(None, description="Firmware version")
    last_sync_at: datetime | None = Field(None, description="Last sync time")


class DataCoverage(BaseModel):
    """Data coverage information for a metric."""

    data_type: str = Field(description="Type of data")
    first_date: str | None = Field(None, description="First date with data")
    last_date: str | None = Field(None, description="Last date with data")
    days_with_data: int = Field(ge=0, description="Number of days with data")
    gaps_detected: list[tuple[str, str]] = Field(
        default_factory=list, description="Detected date gaps"
    )


class ConnectionStatus(BaseModel):
    """Connection status response."""

    mode: Literal["mi_fitness_cloud", "not_configured"]
    connected: bool
    last_sync_at: datetime | None = None
    available_data_types: list[str] = Field(default_factory=list)
    account_id_masked: str | None = None
    sync_health: Literal["healthy", "stale", "error", "unknown"] = "unknown"
    next_action: str | None = None
    message: str | None = None


class SyncResult(BaseModel):
    """Data synchronization result."""

    sync_id: str = Field(description="Unique sync identifier")
    started_at: datetime = Field(description="Sync start time")
    finished_at: datetime = Field(description="Sync end time")
    records_added: int = Field(ge=0, description="New records added")
    records_updated: int = Field(ge=0, description="Records updated")
    records_skipped: int = Field(ge=0, description="Records skipped (duplicates)")
    data_types_synced: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """Generic query response envelope."""

    status: Literal["ok", "error"] = "ok"
    source: Literal["mi_fitness_cloud", "cloud_session", "cache", "unknown"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    timezone: str = "UTC"
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
