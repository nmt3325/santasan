import asyncio
import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    actions_per_hour: int = 40
    new_account_actions_per_hour: int = 20
    follows_per_hour: int = 8
    follows_per_day: int = 400
    likes_per_day_total: int = 100
    reposts_per_day_total: int = 50
    replies_per_day_total: int = 30
    organic_tweets_per_day_min: int = 2
    organic_tweets_per_day_max: int = 5
    min_delay_seconds: float = 300.0
    max_delay_seconds: float = 1800.0
    active_window_hours: int = 14
    backoff_base: float = 60.0
    backoff_max: float = 480.0
    backoff_multiplier: float = 2.0

    @classmethod
    def from_dict(cls, d: dict) -> "RateLimitConfig":
        rl = d.get("rate_limits", {})
        bk = d.get("backoff", {})
        return cls(
            actions_per_hour=rl.get("actions_per_hour", 40),
            new_account_actions_per_hour=rl.get("new_account_actions_per_hour", 20),
            follows_per_hour=rl.get("follows_per_hour", 8),
            follows_per_day=rl.get("follows_per_day", 400),
            likes_per_day_total=rl.get("likes_per_day_total", 100),
            reposts_per_day_total=rl.get("reposts_per_day_total", 50),
            replies_per_day_total=rl.get("replies_per_day_total", 30),
            organic_tweets_per_day_min=rl.get("organic_tweets_per_day_min", 2),
            organic_tweets_per_day_max=rl.get("organic_tweets_per_day_max", 5),
            min_delay_seconds=rl.get("min_delay_seconds", 300),
            max_delay_seconds=rl.get("max_delay_seconds", 1800),
            active_window_hours=rl.get("active_window_hours", 14),
            backoff_base=bk.get("base_seconds", 60),
            backoff_max=bk.get("max_seconds", 480),
            backoff_multiplier=bk.get("multiplier", 2),
        )


class AccountRateTracker:
    def __init__(self, account_name: str, is_new: bool, cfg: RateLimitConfig):
        self.name = account_name
        self.is_new = is_new
        self.cfg = cfg
        self._hourly_timestamps: list[datetime] = []
        self._follow_timestamps: list[datetime] = []
        self._daily: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._backoff_seconds: float = 0.0

    def _today(self) -> date:
        return datetime.now(tz=timezone.utc).date()

    def _prune_hourly(self) -> None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        self._hourly_timestamps = [t for t in self._hourly_timestamps if t > cutoff]
        self._follow_timestamps = [t for t in self._follow_timestamps if t > cutoff]

    def _hourly_limit(self) -> int:
        return self.cfg.new_account_actions_per_hour if self.is_new else self.cfg.actions_per_hour

    def can_act(self) -> bool:
        self._prune_hourly()
        return len(self._hourly_timestamps) < self._hourly_limit()

    def can_follow(self) -> bool:
        self._prune_hourly()
        return (
            len(self._follow_timestamps) < self.cfg.follows_per_hour
            and self._daily[self._today()]["follow"] < self.cfg.follows_per_day
        )

    def record_action(self, action_type: str) -> None:
        now = datetime.now(tz=timezone.utc)
        self._hourly_timestamps.append(now)
        if action_type == "follow":
            self._follow_timestamps.append(now)
        self._daily[self._today()][action_type] += 1

    def daily_count(self, action_type: str) -> int:
        return self._daily[self._today()][action_type]

    def set_backoff(self, seconds: float) -> None:
        self._backoff_seconds = seconds

    async def consume_backoff(self) -> None:
        if self._backoff_seconds > 0:
            logger.info("[%s] Backing off for %.0fs", self.name, self._backoff_seconds)
            await asyncio.sleep(self._backoff_seconds)
            self._backoff_seconds = 0.0

    def escalate_backoff(self) -> float:
        current = self._backoff_seconds or self.cfg.backoff_base
        self._backoff_seconds = min(current * self.cfg.backoff_multiplier, self.cfg.backoff_max)
        return self._backoff_seconds

    def reset_backoff(self) -> None:
        self._backoff_seconds = 0.0


class GlobalRateTracker:
    def __init__(self, cfg: RateLimitConfig):
        self.cfg = cfg
        self._today_date: date | None = None
        self._likes_today: int = 0
        self._reposts_today: int = 0
        self._replies_today: int = 0

    def _maybe_reset(self) -> None:
        today = datetime.now(tz=timezone.utc).date()
        if today != self._today_date:
            self._today_date = today
            self._likes_today = 0
            self._reposts_today = 0
            self._replies_today = 0

    def can_like(self) -> bool:
        self._maybe_reset()
        return self._likes_today < self.cfg.likes_per_day_total

    def can_repost(self) -> bool:
        self._maybe_reset()
        return self._reposts_today < self.cfg.reposts_per_day_total

    def can_reply(self) -> bool:
        self._maybe_reset()
        return self._replies_today < self.cfg.replies_per_day_total

    def record_like(self) -> None:
        self._maybe_reset()
        self._likes_today += 1

    def record_repost(self) -> None:
        self._maybe_reset()
        self._reposts_today += 1

    def record_reply(self) -> None:
        self._maybe_reset()
        self._replies_today += 1


async def jitter_delay(cfg: RateLimitConfig) -> None:
    delay = random.uniform(cfg.min_delay_seconds, cfg.max_delay_seconds)
    logger.debug("Jitter delay: %.0fs", delay)
    await asyncio.sleep(delay)


async def run_with_backoff(
    coro_fn: Callable[[], Awaitable[bool]],
    tracker: AccountRateTracker,
) -> bool:
    await tracker.consume_backoff()
    success = await coro_fn()
    if success:
        tracker.reset_backoff()
    else:
        wait = tracker.escalate_backoff()
        logger.warning("[%s] Action failed, next backoff: %.0fs", tracker.name, wait)
    return success
