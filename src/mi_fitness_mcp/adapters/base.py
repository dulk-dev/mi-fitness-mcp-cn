"""Base adapter interface for data sources."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Coroutine, Iterator
from typing import Any, Union

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


class DataAdapter(ABC):
    """Abstract base class for data source adapters."""

    @abstractmethod
    def connect(self) -> Union[bool, "Coroutine[Any, Any, bool]"]:
        """Connect to data source.

        Returns:
            True if connection successful
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to data source."""
        pass

    @abstractmethod
    def get_user_id(self) -> str | None:
        """Get user identifier from data source."""
        pass

    @abstractmethod
    def iter_daily_activity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[DailyActivity] | AsyncIterator[DailyActivity]:
        """Iterate over daily activity records."""
        pass

    @abstractmethod
    def iter_sleep_sessions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[SleepSession] | AsyncIterator[SleepSession]:
        """Iterate over sleep session records."""
        pass

    @abstractmethod
    def iter_workouts(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[Workout] | AsyncIterator[Workout]:
        """Iterate over workout records."""
        pass

    @abstractmethod
    def iter_body_measurements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[BodyMeasurement] | AsyncIterator[BodyMeasurement]:
        """Iterate over body measurement records."""
        pass

    @abstractmethod
    def iter_heart_rate(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[HeartRateSample] | AsyncIterator[HeartRateSample]:
        """Iterate over heart rate records."""
        pass

    @abstractmethod
    def iter_spo2(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[SpO2Sample] | AsyncIterator[SpO2Sample]:
        """Iterate over blood oxygen saturation records."""
        pass

    @abstractmethod
    def iter_stress(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[StressSample] | AsyncIterator[StressSample]:
        """Iterate over stress records."""
        pass

    @abstractmethod
    def iter_abnormal_heart_beat(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[AbnormalHeartBeatEvent] | AsyncIterator[AbnormalHeartBeatEvent]:
        """Iterate over abnormal heart beat events."""
        pass

    @abstractmethod
    def iter_pai(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[PaiDaily] | AsyncIterator[PaiDaily]:
        """Iterate over daily PAI records."""
        pass

    @abstractmethod
    def iter_stand_hours(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[StandHour] | AsyncIterator[StandHour]:
        """Iterate over hourly standing segments."""
        pass

    @abstractmethod
    def iter_stand_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[StandDaily] | AsyncIterator[StandDaily]:
        """Iterate over daily standing-hour counts."""
        pass

    @abstractmethod
    def iter_menstruation(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[MenstruationEvent] | AsyncIterator[MenstruationEvent]:
        """Iterate over menstruation start/end markers."""
        pass

    @abstractmethod
    def iter_training_load(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[TrainingLoadDaily] | AsyncIterator[TrainingLoadDaily]:
        """Iterate over daily training-load records."""
        pass

    @abstractmethod
    def iter_intensity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[IntensitySample] | AsyncIterator[IntensitySample]:
        """Iterate over intensity samples."""
        pass

    @abstractmethod
    def iter_intensity_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[IntensityDaily] | AsyncIterator[IntensityDaily]:
        """Iterate over daily intensity durations."""
        pass

    @abstractmethod
    def get_available_data_types(self) -> list[str]:
        """Get list of available data types."""
        pass
