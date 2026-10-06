import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import struct
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from mi_fitness_mcp.adapters.base import DataAdapter
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
    SleepStage,
    SpO2Sample,
    StandDaily,
    StandHour,
    StressSample,
    TrainingLoadDaily,
    Workout,
)

SUPPORTED_DATA_TYPES = [
    "daily_activity",
    "heart_rate",
    "body_measurements",
    "sleep",
    "workouts",
    "spo2",
    "stress",
    "abnormal_heart_beat",
    "pai",
    "valid_stand",
    "menstruation",
    "training_load",
    "intensity",
]
MENSTRUATION_STATUS = {1: "start", 2: "end", 3: "both"}

LOGIN_PREFIX = b"&&&START&&&"
KNOWN_REGIONS = ["ru", "cn", "de", "i2", "sg", "us"]
AUTH_ERROR_MARKERS = (
    "authentication failed",
    "invalid credential",
    "invalid pass token",
    "invalid passtoken",
    "login required",
    "not logged in",
    "session expired",
    "unauthorized",
)
logger = logging.getLogger(__name__)


class MiFitnessAuthenticationError(RuntimeError):
    """The Xiaomi cloud session is no longer authenticated."""


def _is_authentication_error(code: Any, message: str) -> bool:
    normalized = message.casefold()
    return code in {401, 403, -6, -10001} or any(
        marker in normalized for marker in AUTH_ERROR_MARKERS
    )


def _read_login_payload(text: str) -> dict:
    payload = text.encode()
    if not payload.startswith(LOGIN_PREFIX):
        raise RuntimeError("unexpected Xiaomi login response")
    return json.loads(payload[len(LOGIN_PREFIX) :].decode())


def _rc4_crypt(key: bytes, payload: bytes) -> bytes:
    s = list(range(256))
    j = 0
    key_len = len(key)
    for i in range(256):
        j = (j + s[i] + key[i % key_len]) % 256
        s[i], s[j] = s[j], s[i]
    i = 0
    j = 0

    def next_byte() -> int:
        nonlocal i, j
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        return s[(s[i] + s[j]) % 256]

    for _ in range(1024):
        next_byte()

    output = bytearray()
    for value in payload:
        output.append(value ^ next_byte())
    return bytes(output)


def _gen_nonce() -> bytes:
    raw = bytearray(os.urandom(8))
    raw.extend(struct.pack(">I", int(datetime.now().timestamp() // 60)))
    return bytes(raw)


def _gen_signed_nonce(ssecurity: bytes, nonce: bytes) -> bytes:
    return hashlib.sha256(ssecurity + nonce).digest()


def _gen_signature(method: str, path: str, values: dict[str, str], signed_nonce: bytes) -> str:
    base = method + "&" + path + "&data=" + values["data"]
    if "rc4_hash__" in values:
        base += "&rc4_hash__=" + values["rc4_hash__"]
    base += "&" + base64.b64encode(signed_nonce).decode()
    return base64.b64encode(hashlib.sha1(base.encode()).digest()).decode()


class MiFitnessCloudAdapter(DataAdapter):
    def __init__(
        self, user_id: str | None = None, pass_token: str | None = None, region: str = "ru"
    ):
        self.user_id = user_id
        self.pass_token = pass_token
        self.region = region
        self._cookies = ""
        self._ssecurity = b""
        self._client: httpx.AsyncClient | None = None
        self._connected = False
        self._available_types: list[str] = []
        self._connect_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.last_health_check_at: datetime | None = None
        self.max_pages = 200
        self.request_retries = 3
        self.http_timeout = 20.0

    async def connect(self) -> bool:
        async with self._connect_lock:
            if not self.user_id or not self.pass_token:
                self.last_error = "Missing Mi Fitness credentials"
                self._connected = False
                return False
            await self._close_client()
            self._client = httpx.AsyncClient(
                timeout=self.http_timeout,
                follow_redirects=False,
                # 浏览器 UA 与 Cookie 登录来源一致，避免暴露 python-httpx 指纹
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                },
            )
            try:
                await self._login_with_token(self.user_id, self.pass_token)
                # Trust an explicitly configured region. Expensive cross-region discovery
                # made MCP startup exceed host initialization timeouts.
                if not self.region:
                    self.region = await self._discover_region("cn")
                self._available_types = await self._discover_data_types()
                self._connected = True
                self.last_error = None
                return True
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Mi Fitness connection failed: %s", self.last_error)
                self._connected = False
                await self._close_client()
                return False

    async def health_check(self) -> bool:
        self.last_health_check_at = datetime.now(UTC)
        if not self.is_connected():
            return await self.connect()
        try:
            # A one-day query is small and verifies authentication and the data API.
            today = datetime.now(self._request_timezone()).date().isoformat()
            await self._fetch_key("steps", today, today)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            # Request handling already marks explicit HTTP authentication failures
            # disconnected. Keep a valid session on transient network/API failures.
            return False

    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    def get_user_id(self) -> str | None:
        return self.user_id

    def get_available_data_types(self) -> list[str]:
        return self._available_types.copy()

    async def _close_client(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _login_with_token(self, user_id: str, pass_token: str) -> None:
        if not self._client:
            raise RuntimeError("client not initialized")

        response = await self._client.get(
            "https://account.xiaomi.com/pass/serviceLogin?_json=true&sid=miothealth",
            headers={"Cookie": f"userId={user_id}; passToken={pass_token}"},
        )
        response.raise_for_status()
        payload = _read_login_payload(response.text)
        self.pass_token = payload["passToken"]
        self.user_id = str(payload["userId"])
        self._ssecurity = base64.b64decode(payload["ssecurity"])

        redirect = await self._client.get(payload["location"])
        redirect.raise_for_status()
        cookie_parts = [value.split(";", 1)[0] for value in redirect.headers.get_list("set-cookie")]
        self._cookies = "; ".join(cookie_parts)

    async def _request(self, base_url: str, api_path: str, payload: dict) -> dict:
        if not self._client:
            raise RuntimeError("client not initialized")

        last_error: Exception | None = None
        for attempt in range(self.request_retries):
            try:
                form = {"data": json.dumps(payload, separators=(",", ":"))}
                nonce = _gen_nonce()
                signed_nonce = _gen_signed_nonce(self._ssecurity, nonce)
                form["rc4_hash__"] = _gen_signature("POST", api_path, form, signed_nonce)

                encrypted: dict[str, str] = {}
                for key, value in form.items():
                    encrypted[key] = base64.b64encode(
                        _rc4_crypt(signed_nonce, value.encode())
                    ).decode()

                encrypted["signature"] = _gen_signature("POST", api_path, encrypted, signed_nonce)
                encrypted["_nonce"] = base64.b64encode(nonce).decode()

                response = await self._client.post(
                    base_url + api_path,
                    headers={
                        "Cookie": self._cookies,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    content=urlencode(encrypted),
                )
                response.raise_for_status()
                plaintext = _rc4_crypt(signed_nonce, base64.b64decode(response.text))
                body = json.loads(plaintext)
                if body.get("code") != 0:
                    message = str(body.get("message", "unknown mi fitness error"))
                    if _is_authentication_error(body.get("code"), message):
                        raise MiFitnessAuthenticationError(message)
                    raise RuntimeError(message)
                return body.get("result", {})
            except Exception as exc:
                last_error = exc
                retryable = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
                authentication_error = isinstance(exc, MiFitnessAuthenticationError)
                if isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code
                    authentication_error = status in (401, 403)
                    if not authentication_error:
                        retryable = status == 429 or status >= 500
                if authentication_error:
                    self._connected = False
                    if attempt < self.request_retries - 1 and self.user_id and self.pass_token:
                        try:
                            await self._login_with_token(self.user_id, self.pass_token)
                            self._connected = True
                            retryable = True
                        except Exception as login_exc:
                            self.last_error = f"Authentication refresh failed: {login_exc}"
                            retryable = False
                    else:
                        retryable = False
                if attempt == self.request_retries - 1 or not retryable:
                    break
                await asyncio.sleep(min(4.0, 0.5 * (2**attempt)) + random.random() * 0.1)
        if isinstance(last_error, MiFitnessAuthenticationError):
            raise last_error
        raise RuntimeError(f"Mi Fitness request failed: {last_error}") from last_error

    def _request_timezone(self, region: str | None = None) -> timezone:
        region_name = self.region if region is None else region
        if region_name in ("", "cn"):
            return timezone(timedelta(hours=8))
        return UTC

    def _date_range_to_timestamps(
        self, start_date: str, end_date: str, region: str | None = None
    ) -> tuple[int, int]:
        tz = self._request_timezone(region)
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=tz)
        end_dt = datetime.fromisoformat(end_date + "T23:59:59").replace(tzinfo=tz)
        return int(start_dt.timestamp()), int(end_dt.timestamp())

    async def _fetch_key(
        self, key: str, start_date: str, end_date: str, region: str | None = None
    ) -> list[dict]:
        region_name = region or self.region
        base_url = (
            "https://hlth.io.mi.com"
            if region_name in ("", "cn")
            else f"https://{region_name}.hlth.io.mi.com"
        )
        start_time, end_time = self._date_range_to_timestamps(start_date, end_date, region_name)
        next_key = None
        items: list[dict] = []

        seen_keys: set[str] = set()
        page = 0
        while True:
            page += 1
            if page > self.max_pages:
                raise RuntimeError("Mi Fitness pagination exceeded safety limit")
            payload = {
                "start_time": start_time,
                "end_time": end_time,
                "key": key,
            }
            if next_key:
                payload["next_key"] = next_key

            result = await self._request(base_url, "/app/v1/data/get_fitness_data_by_time", payload)
            items.extend(result.get("data_list", []))
            if not result.get("has_more") or not result.get("next_key"):
                break
            candidate = str(result.get("next_key"))
            if candidate in seen_keys:
                raise RuntimeError("Mi Fitness pagination cursor loop detected")
            seen_keys.add(candidate)
            next_key = candidate

        return items

    async def _fetch_aggregated(
        self,
        key: str,
        start_date: str,
        end_date: str,
        tag: str = "daily_report",
        region: str | None = None,
    ) -> list[dict]:
        """Page daily_report rows from get_aggregated_fitness_data_by_time."""
        region_name = region or self.region
        base_url = (
            "https://hlth.io.mi.com"
            if region_name in ("", "cn")
            else f"https://{region_name}.hlth.io.mi.com"
        )
        start_time, end_time = self._date_range_to_timestamps(start_date, end_date, region_name)
        next_key = None
        items: list[dict] = []
        seen_keys: set[str] = set()
        page = 0
        while True:
            page += 1
            if page > self.max_pages:
                raise RuntimeError("Mi Fitness aggregated pagination exceeded safety limit")
            payload: dict[str, Any] = {
                "key": key,
                "tag": tag,
                "start_time": start_time,
                "end_time": end_time,
                "limit": 100,
            }
            if next_key:
                payload["next_key"] = next_key
            result = await self._request(
                base_url, "/app/v1/data/get_aggregated_fitness_data_by_time", payload
            )
            items.extend(result.get("data_list", []))
            if not result.get("has_more") or not result.get("next_key"):
                break
            candidate = str(result.get("next_key"))
            if candidate in seen_keys:
                raise RuntimeError("Mi Fitness aggregated pagination cursor loop detected")
            seen_keys.add(candidate)
            next_key = candidate
        return items

    async def _discover_region(self, preferred_region: str) -> str:
        candidates = [preferred_region] + [
            region for region in KNOWN_REGIONS if region != preferred_region
        ]
        for region in candidates:
            for key in ("weight", "steps", "heart_rate"):
                try:
                    result = await self._fetch_key(key, "2025-04-01", "2025-05-31", region=region)
                    if result:
                        return region
                except Exception:
                    continue
        return preferred_region

    async def _discover_data_types(self) -> list[str]:
        # 小米健康云没有可靠的能力发现接口。旧实现用固定历史区间探测，
        # 当该区间无数据时会导致自动同步静默跳过大部分指标。
        # 这里直接返回本适配器支持的全部数据类型；某类型无记录时同步 0 条即可，
        # 比漏掉近期数据更安全。
        return list(SUPPORTED_DATA_TYPES)

    def _record_datetime(self, item: dict) -> datetime:
        timestamp = int(item.get("time", 0))
        zone_offset = int(item.get("zone_offset", 0) or 0)
        tz = timezone(timedelta(seconds=zone_offset))
        return datetime.fromtimestamp(timestamp, tz=tz)

    def _parse_value(self, item: dict) -> dict[str, Any]:
        raw = item.get("value", "{}")
        if isinstance(raw, dict):
            return raw
        return json.loads(raw)

    def _timestamp_to_datetime(self, timestamp: Any, zone_offset: int = 0) -> datetime:
        tz = timezone(timedelta(seconds=int(zone_offset or 0)))
        return datetime.fromtimestamp(int(timestamp), tz=tz)

    async def _fetch_sport_records_by_time(
        self, start_date: str, end_date: str, region: str | None = None
    ) -> list[dict]:
        region_name = region or self.region
        base_url = (
            "https://hlth.io.mi.com"
            if region_name in ("", "cn")
            else f"https://{region_name}.hlth.io.mi.com"
        )
        start_time, end_time = self._date_range_to_timestamps(start_date, end_date, region_name)
        next_key = None
        items: list[dict] = []

        seen_keys: set[str] = set()
        page = 0
        while True:
            page += 1
            if page > self.max_pages:
                raise RuntimeError("Mi Fitness sport pagination exceeded safety limit")
            payload: dict[str, Any] = {
                "start_time": start_time,
                "end_time": end_time,
                "limit": 50,
            }
            if next_key:
                payload["next_key"] = next_key

            result = await self._request(
                base_url, "/app/v1/data/get_sport_records_by_time", payload
            )
            items.extend(result.get("sport_records", []))
            if not result.get("has_more") or not result.get("next_key"):
                break
            candidate = str(result.get("next_key"))
            if candidate in seen_keys:
                raise RuntimeError("Mi Fitness sport pagination cursor loop detected")
            seen_keys.add(candidate)
            next_key = candidate

        return items

    def _sleep_stage_name(self, state: Any) -> str:
        mapping = {
            1: "deep",
            2: "light",
            3: "light",
            4: "awake",
            5: "rem",
        }
        try:
            return mapping.get(int(state), "light")
        except Exception:
            return "light"

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        parsed = float(value)
        return None if parsed == 0 else parsed

    def _optional_int(self, value: Any) -> int | None:
        if value is None:
            return None
        parsed = int(float(value))
        return None if parsed == 0 else parsed

    def _finite_float(self, value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number

    def _finite_int(self, value: Any) -> int | None:
        number = self._finite_float(value)
        if number is None:
            return None
        return int(number)

    def _zone_offset(self, item: dict) -> int:
        raw = int(item.get("zone_offset") or 0)
        if raw:
            return raw
        delta = self._request_timezone().utcoffset(None)
        return int(delta.total_seconds()) if delta else 0

    def _coerce_datetime(self, value: Any, zone_offset: int) -> datetime | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, str):
            text = value.strip()
            if len(text) >= 10 and text[4] == "-" and text[7] == "-":
                try:
                    parsed = datetime.fromisoformat(text)
                except ValueError:
                    return None
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone(timedelta(seconds=zone_offset)))
                return parsed
            if not text.isdigit():
                return None
            value = int(text)
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        if timestamp <= 0:
            return None
        return self._timestamp_to_datetime(timestamp, zone_offset)

    def _calendar_date(self, item: dict, payload: dict, *keys: str) -> tuple[str, datetime] | None:
        offset = self._zone_offset(item)
        when = None
        for key in keys:
            when = self._coerce_datetime(payload.get(key), offset)
            if when is not None:
                break
        if when is None and item.get("time"):
            when = self._coerce_datetime(item.get("time"), offset)
        if when is None:
            return None
        return when.strftime("%Y-%m-%d"), when

    def _base_record(self, item: dict, record_id: str, collected_at: datetime) -> dict[str, Any]:
        return {
            "id": record_id,
            "provider": "mi_fitness",
            "source_type": "cloud_session",
            "source_record_id": str(item.get("time", "")) or None,
            "user_id": self.user_id or "unknown",
            "timezone": item.get("zone_name")
            or ("Asia/Shanghai" if self.region in ("", "cn") else "UTC"),
            "collected_at": collected_at,
        }

    def _sleep_score_value(self, payload: dict) -> int | None:
        for name in ("sleep_score", "score"):
            value = payload.get(name)
            if isinstance(value, bool) or value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number.is_integer() and 0 < number <= 100:
                return int(number)
        return None

    def _report_sleep_score(self, payload: dict) -> int | None:
        score = self._sleep_score_value(payload)
        if score is not None:
            return score
        segments = payload.get("segment_details")
        if not isinstance(segments, list):
            return None
        best_score = None
        best_length = -1
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            segment_score = self._sleep_score_value(segment)
            if segment_score is None:
                continue
            try:
                start = int(segment.get("bedtime") or segment.get("start_time") or 0)
                end = int(segment.get("wake_up_time") or segment.get("end_time") or 0)
                length = end - start
            except (TypeError, ValueError):
                length = 0
            if length >= best_length:
                best_length = length
                best_score = segment_score
        return best_score

    def _attach_sleep_scores(self, sessions: list[SleepSession], reports: list[dict]) -> None:
        """Fill empty sleep_score from the daily sleep report for one main session."""
        scores_by_day: dict[str, set[int]] = defaultdict(set)
        for item in reports:
            if not isinstance(item, dict) or not item.get("time"):
                continue
            try:
                payload = self._parse_value(item)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            score = self._report_sleep_score(payload)
            if score is None:
                continue
            when = self._coerce_datetime(item.get("time"), self._zone_offset(item))
            if when is None:
                continue
            scores_by_day[when.strftime("%Y-%m-%d")].add(score)

        for day, scores in scores_by_day.items():
            if len(scores) != 1:
                continue
            score = next(iter(scores))
            candidates = [
                session
                for session in sessions
                if session.sleep_score is None
                and not session.is_nap
                and session.end_at.strftime("%Y-%m-%d") == day
            ]
            if len(candidates) == 1:
                candidates[0].sleep_score = score
                continue
            if not candidates:
                continue
            longest = max(candidates, key=lambda session: session.duration_minutes)
            if (
                sum(session.duration_minutes == longest.duration_minutes for session in candidates)
                == 1
            ):
                longest.sleep_score = score

    async def iter_daily_activity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[DailyActivity]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("steps", start_date, end_date)
        daily: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "steps": 0,
                "distance_m": 0.0,
                "active_kcal": 0.0,
                "timezone": "UTC",
                "collected_at": None,
            }
        )
        for item in records:
            payload = self._parse_value(item)
            collected_at = self._record_datetime(item)
            date_str = collected_at.strftime("%Y-%m-%d")
            daily[date_str]["steps"] += int(payload.get("steps", 0))
            daily[date_str]["distance_m"] += float(payload.get("distance", 0))
            daily[date_str]["active_kcal"] += float(payload.get("calories", 0))
            daily[date_str]["timezone"] = item.get("zone_name") or daily[date_str]["timezone"]
            if (
                daily[date_str]["collected_at"] is None
                or collected_at > daily[date_str]["collected_at"]
            ):
                daily[date_str]["collected_at"] = collected_at

        calorie_records = await self._fetch_key("calories", start_date, end_date)
        calorie_totals: dict[str, float] = defaultdict(float)
        for item in calorie_records:
            payload = self._parse_value(item)
            collected_at = self._record_datetime(item)
            date_str = collected_at.strftime("%Y-%m-%d")
            calorie_totals[date_str] += float(payload.get("calories", 0))
            daily[date_str]["timezone"] = item.get("zone_name") or daily[date_str]["timezone"]
            if (
                daily[date_str]["collected_at"] is None
                or collected_at > daily[date_str]["collected_at"]
            ):
                daily[date_str]["collected_at"] = collected_at

        for date_str, total in calorie_totals.items():
            daily[date_str]["active_kcal"] = total

        for date_str, values in sorted(daily.items()):
            yield DailyActivity(
                id=f"mi_fitness_activity_{date_str}",
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=self.user_id or "unknown",
                timezone=str(values["timezone"]),
                collected_at=values["collected_at"],
                date=date_str,
                steps=int(values["steps"]),
                distance_m=float(values["distance_m"]),
                active_kcal=float(values["active_kcal"]),
            )

    async def iter_sleep_sessions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[SleepSession]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("sleep", start_date, end_date)
        # 2026-10: new overnight sleep is stored under "watch_night_sleep" (Vita patch)
        records = list(records) + list(
            await self._fetch_key("watch_night_sleep", start_date, end_date)
        )
        sessions: list[SleepSession] = []
        for item in records:
            payload = self._parse_value(item)
            # watch_night_sleep items carry no zone_offset; default to UTC+8 (cn) (Vita patch)
            zone_offset = int(item.get("zone_offset", 0) or 0) or 28800
            sleep_start = (
                payload.get("bedtime")
                or payload.get("device_bedtime")
                or payload.get("bed_timestamp")
            )
            sleep_end = (
                payload.get("wake_up_time")
                or payload.get("device_wake_up_time")
                or payload.get("out_bed_timestamp")
                or item.get("time")
            )
            if not sleep_start or not sleep_end:
                continue

            start_at = self._timestamp_to_datetime(sleep_start, zone_offset)
            end_at = self._timestamp_to_datetime(sleep_end, zone_offset)
            duration_minutes = int(
                payload.get("duration") or max(0, (int(sleep_end) - int(sleep_start)) // 60)
            )
            awake_minutes = int(
                payload.get("awake_duration") or payload.get("sleep_awake_duration") or 0
            )
            asleep_minutes = max(0, duration_minutes - awake_minutes)

            stages: list[SleepStage] = []
            for segment in payload.get("items", []) or []:
                try:
                    seg_start = int(segment.get("start_time", 0))
                    seg_end = int(segment.get("end_time", 0))
                    minutes = max(0, (seg_end - seg_start) // 60)
                    if minutes:
                        stages.append(
                            SleepStage(
                                stage=self._sleep_stage_name(segment.get("state")), minutes=minutes
                            )
                        )
                except Exception:
                    continue

            sleep_id = f"{item.get('sid', self.user_id)}_{item.get('time', int(sleep_end))}"
            sessions.append(
                SleepSession(
                    id=f"mi_fitness_sleep_{sleep_id}",
                    provider="mi_fitness",
                    source_type="cloud_session",
                    source_record_id=str(item.get("time", "")) or None,
                    user_id=self.user_id or "unknown",
                    timezone=item.get("zone_name") or "Asia/Shanghai",
                    collected_at=self._record_datetime(item),
                    sleep_id=sleep_id,
                    start_at=start_at,
                    end_at=end_at,
                    duration_minutes=duration_minutes,
                    time_asleep_minutes=asleep_minutes,
                    time_awake_minutes=awake_minutes,
                    sleep_score=self._optional_int(
                        payload.get("score") or payload.get("sleep_score")
                    ),
                    is_nap=bool(payload.get("is_nap", False)),
                    stages=stages,
                )
            )

        if any(session.sleep_score is None and not session.is_nap for session in sessions):
            try:
                reports = await self._fetch_aggregated("sleep", start_date, end_date)
            except Exception:
                logger.warning("Mi Fitness daily sleep report unavailable; sleep_score left empty")
                reports = []
            self._attach_sleep_scores(sessions, reports)
        for session in sessions:
            yield session

    async def iter_workouts(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[Workout]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_sport_records_by_time(start_date, end_date)
        for item in records:
            payload = self._parse_value(item)
            zone_offset = int(item.get("zone_offset", 0) or 0)
            start_ts = payload.get("start_time") or item.get("time")
            end_ts = payload.get("end_time")
            duration_seconds = int(payload.get("duration", 0) or 0)
            if not end_ts and start_ts:
                end_ts = int(start_ts) + duration_seconds
            if not start_ts or not end_ts:
                continue

            start_at = self._timestamp_to_datetime(start_ts, zone_offset)
            end_at = self._timestamp_to_datetime(end_ts, zone_offset)
            duration_minutes = max(0, int(duration_seconds // 60))
            if duration_minutes == 0:
                duration_minutes = max(0, (int(end_ts) - int(start_ts)) // 60)

            workout_id = f"{item.get('sid', self.user_id)}_{item.get('key', 'workout')}_{item.get('time', start_ts)}"
            yield Workout(
                id=f"mi_fitness_workout_{workout_id}",
                provider="mi_fitness",
                source_type="cloud_session",
                source_record_id=str(item.get("time", "")) or None,
                user_id=self.user_id or "unknown",
                timezone=item.get("zone_name") or "UTC",
                collected_at=self._record_datetime(item),
                workout_id=workout_id,
                activity_type=str(
                    item.get("category")
                    or item.get("key")
                    or payload.get("sport_type")
                    or "workout"
                ),
                start_at=start_at,
                end_at=end_at,
                duration_minutes=duration_minutes,
                distance_m=self._optional_float(payload.get("distance")),
                calories_kcal=self._optional_float(
                    payload.get("calories") or payload.get("total_cal")
                ),
                avg_heart_rate_bpm=self._optional_int(payload.get("avg_hrm")),
                max_heart_rate_bpm=self._optional_int(payload.get("max_hrm")),
                avg_pace_sec_per_km=self._optional_float(payload.get("avg_pace")),
                max_pace_sec_per_km=self._optional_float(payload.get("max_pace")),
                total_steps=self._optional_int(payload.get("steps") or payload.get("total_steps")),
            )

    async def iter_body_measurements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[BodyMeasurement]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("weight", start_date, end_date)
        for item in records:
            payload = self._parse_value(item)
            measured_at = self._record_datetime(item)
            yield BodyMeasurement(
                id=f"mi_fitness_weight_{int(item.get('time', 0))}",
                provider="mi_fitness",
                source_type="cloud_session",
                user_id=self.user_id or "unknown",
                timestamp=measured_at,
                weight_kg=float(payload.get("weight", 0)),
                bmi=float(payload["bmi"]) if payload.get("bmi") is not None else None,
                body_fat_pct=self._optional_float(payload.get("body_fat_rate")),
                muscle_mass_kg=self._optional_float(payload.get("muscle_rate")),
                water_pct=self._optional_float(payload.get("moisture_rate")),
                bone_mass_kg=self._optional_float(payload.get("bone_mass")),
                visceral_fat_score=self._optional_int(payload.get("visceral_fat")),
                basal_metabolism_kcal=self._optional_int(payload.get("basal_metabolism")),
                metabolic_age=self._optional_int(payload.get("body_age")),
            )

    async def iter_heart_rate(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[HeartRateSample]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("heart_rate", start_date, end_date)
        for item in records:
            payload = self._parse_value(item)
            sample_type = "passive" if int(payload.get("type", 0)) == 0 else "active"
            yield HeartRateSample(
                id=f"mi_fitness_hr_{int(item.get('time', 0))}",
                provider="mi_fitness",
                source_type="cloud_session",
                source_record_id=str(item.get("time", "")) or None,
                user_id=self.user_id or "unknown",
                timezone=item.get("zone_name") or "UTC",
                collected_at=self._record_datetime(item),
                timestamp=self._record_datetime(item),
                bpm=int(payload.get("bpm", 0)),
                sample_type=sample_type,
            )

        resting_records = await self._fetch_key("resting_heart_rate", start_date, end_date)
        for item in resting_records:
            payload = self._parse_value(item)
            timestamp = payload.get("date_time") or item.get("time")
            yield HeartRateSample(
                id=f"mi_fitness_resting_hr_{int(timestamp or item.get('time', 0))}",
                provider="mi_fitness",
                source_type="cloud_session",
                source_record_id=str(item.get("time", "")) or None,
                user_id=self.user_id or "unknown",
                timezone=item.get("zone_name") or "UTC",
                collected_at=self._record_datetime(item),
                timestamp=self._timestamp_to_datetime(
                    timestamp or item.get("time"), int(item.get("zone_offset", 0) or 0)
                ),
                bpm=int(payload.get("bpm", 0)),
                sample_type="resting",
            )

    def _stress_level(self, score: int) -> str:
        if score < 30:
            return "low"
        if score < 60:
            return "medium"
        return "high"

    async def iter_spo2(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[SpO2Sample]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("spo2", start_date, end_date)
        # 2026-10: SpO2 samples live under "single_spo2" (Vita patch)
        records = list(records) + list(await self._fetch_key("single_spo2", start_date, end_date))
        for item in records:
            payload = self._parse_value(item)
            timestamp = payload.get("time") or item.get("time")
            spo2 = payload.get("spo2") or payload.get("value")
            if timestamp is None or spo2 is None:
                continue
            yield SpO2Sample(
                id=f"mi_fitness_spo2_{int(timestamp)}",
                provider="mi_fitness",
                source_type="cloud_session",
                source_record_id=str(item.get("time", "")) or None,
                user_id=self.user_id or "unknown",
                timezone=item.get("zone_name") or "UTC",
                collected_at=self._record_datetime(item),
                timestamp=self._timestamp_to_datetime(
                    timestamp, int(item.get("zone_offset", 0) or 0)
                ),
                spo2_pct=int(float(spo2)),
            )

    async def iter_stress(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[StressSample]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("stress", start_date, end_date)
        for item in records:
            payload = self._parse_value(item)
            timestamp = payload.get("time") or item.get("time")
            stress = payload.get("stress") or payload.get("score") or payload.get("value")
            if timestamp is None or stress is None:
                continue
            score = int(float(stress))
            yield StressSample(
                id=f"mi_fitness_stress_{int(timestamp)}",
                provider="mi_fitness",
                source_type="cloud_session",
                source_record_id=str(item.get("time", "")) or None,
                user_id=self.user_id or "unknown",
                timezone=item.get("zone_name") or "UTC",
                collected_at=self._record_datetime(item),
                timestamp=self._timestamp_to_datetime(
                    timestamp, int(item.get("zone_offset", 0) or 0)
                ),
                stress_score=score,
                level=self._stress_level(score),
            )

    async def iter_abnormal_heart_beat(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[AbnormalHeartBeatEvent]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        records = await self._fetch_key("abnormal_heart_beat", start_date, end_date)
        for item in records:
            payload = self._parse_value(item)
            zone_offset = int(item.get("zone_offset", 0) or 0)
            start_ts = payload.get("start_time") or item.get("time")
            end_ts = payload.get("end_time") or start_ts
            if start_ts is None:
                continue
            start_at = self._timestamp_to_datetime(start_ts, zone_offset)
            end_at = self._timestamp_to_datetime(end_ts, zone_offset)
            duration_seconds = max(0, int(end_ts) - int(start_ts))
            event_id = f"{item.get('sid', self.user_id)}_{int(start_ts)}"
            yield AbnormalHeartBeatEvent(
                id=f"mi_fitness_abnormal_hr_{event_id}",
                provider="mi_fitness",
                source_type="cloud_session",
                source_record_id=str(item.get("time", "")) or None,
                user_id=self.user_id or "unknown",
                timezone=item.get("zone_name") or "UTC",
                collected_at=self._record_datetime(item),
                event_id=event_id,
                start_at=start_at,
                end_at=end_at,
                duration_seconds=duration_seconds,
            )

    async def iter_pai(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[PaiDaily]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_key("pai", start_date, end_date):
            payload = self._parse_value(item)
            located = self._calendar_date(item, payload, "date_time")
            if located is None:
                continue
            date_str, when = located
            daily = self._finite_float(payload.get("daily_pai"))
            total = self._finite_float(payload.get("total_pai"))
            if daily is None and total is None:
                continue
            yield PaiDaily(
                **self._base_record(item, f"mi_fitness_pai_{date_str}", when),
                date=date_str,
                daily_pai=daily or 0.0,
                total_pai=total or 0.0,
                low_zone_pai=self._finite_float(payload.get("low_zone_pai")) or 0.0,
                medium_zone_pai=self._finite_float(payload.get("medium_zone_pai")) or 0.0,
                high_zone_pai=self._finite_float(payload.get("high_zone_pai")) or 0.0,
            )

    async def iter_stand_hours(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[StandHour]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_key("valid_stand", start_date, end_date):
            payload = self._parse_value(item)
            offset = self._zone_offset(item)
            start_at = self._coerce_datetime(payload.get("start_time"), offset)
            if start_at is None:
                continue
            end_at = self._coerce_datetime(payload.get("end_time"), offset) or (
                start_at + timedelta(hours=1)
            )
            stamp = int(start_at.timestamp())
            yield StandHour(
                **self._base_record(item, f"mi_fitness_stand_{stamp}", start_at),
                start_at=start_at,
                end_at=end_at,
            )

    async def iter_stand_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[StandDaily]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_aggregated("valid_stand", start_date, end_date):
            payload = self._parse_value(item)
            count = self._finite_int(payload.get("count"))
            located = self._calendar_date(item, payload)
            if count is None or count < 0 or located is None:
                continue
            date_str, when = located
            yield StandDaily(
                **self._base_record(item, f"mi_fitness_stand_daily_{date_str}", when),
                date=date_str,
                stand_hours=count,
            )

    async def iter_menstruation(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[MenstruationEvent]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_key("menstruation", start_date, end_date):
            payload = self._parse_value(item)
            status = self._finite_int(payload.get("status"))
            if status not in MENSTRUATION_STATUS:
                continue
            located = self._calendar_date(item, payload, "date_time")
            if located is None:
                continue
            date_str, when = located
            offset = self._zone_offset(item)
            updated = self._coerce_datetime(payload.get("update_time"), offset)
            stamp = int(when.timestamp())
            yield MenstruationEvent(
                **self._base_record(item, f"mi_fitness_menstruation_{stamp}_{status}", when),
                event_date=date_str,
                status=status,
                date_time=when,
                update_time=updated,
            )

    async def iter_training_load(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[TrainingLoadDaily]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_key("training_load", start_date, end_date):
            payload = self._parse_value(item)
            values = {
                "current_day_train_load": self._finite_float(payload.get("current_day_train_load")),
                "wtl_sum": self._finite_float(payload.get("wtl_sum")),
                "wtl_sum_optimal_min": self._finite_float(payload.get("wtl_sum_optimal_min")),
                "wtl_sum_optimal_max": self._finite_float(payload.get("wtl_sum_optimal_max")),
                "wtl_sum_overreaching": self._finite_float(payload.get("wtl_sum_overreaching")),
            }
            if all(value is None for value in values.values()):
                continue
            located = self._calendar_date(item, payload, "date_time")
            if located is None:
                continue
            date_str, when = located
            for name, value in values.items():
                if value is not None and value < 0:
                    values[name] = None
            if all(value is None for value in values.values()):
                continue
            yield TrainingLoadDaily(
                **self._base_record(item, f"mi_fitness_training_load_{date_str}", when),
                date=date_str,
                **values,
            )

    async def iter_intensity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[IntensitySample]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_key("intensity", start_date, end_date):
            payload = self._parse_value(item)
            offset = self._zone_offset(item)
            when = self._coerce_datetime(payload.get("time"), offset) or self._coerce_datetime(
                item.get("time"), offset
            )
            if when is None:
                continue
            stamp = int(when.timestamp())
            yield IntensitySample(
                **self._base_record(item, f"mi_fitness_intensity_{stamp}", when),
                timestamp=when,
            )

    async def iter_intensity_daily(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncIterator[IntensityDaily]:
        if not self.is_connected() or not start_date or not end_date:
            return
            yield

        for item in await self._fetch_aggregated("intensity", start_date, end_date):
            payload = self._parse_value(item)
            duration = self._finite_int(payload.get("duration"))
            located = self._calendar_date(item, payload)
            if duration is None or duration < 0 or located is None:
                continue
            date_str, when = located
            yield IntensityDaily(
                **self._base_record(item, f"mi_fitness_intensity_daily_{date_str}", when),
                date=date_str,
                duration_minutes=duration,
            )

    async def close(self) -> None:
        await self._close_client()
        self._connected = False
