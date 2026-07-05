import logging
from datetime import datetime, timezone
from typing import Any

from safe_relay import SafeRelayClient, create_client_from_env

logger = logging.getLogger(__name__)


class ActionsBase:
    """Action facade shared by twikit and Safe Relay clients."""

    def __init__(self, client: Any, account_name: str, dry_run: bool = False):
        self.client = client
        self.account_name = account_name
        self.dry_run = dry_run

    def _log(self, action: str, target_id: str, detail: str = "") -> str:
        ts = datetime.now(tz=timezone.utc).isoformat()
        msg = f"[{ts}] [{self.account_name}] {action} | target={target_id}"
        if detail:
            msg += f" | {detail}"
        if self.dry_run:
            msg += " | DRY_RUN"
        logger.info(msg)
        return msg

    async def follow(self, user_id: str) -> bool:
        self._log("FOLLOW", user_id)
        if self.dry_run:
            return True
        try:
            await self.client.follow_user(user_id)
            return True
        except Exception as e:
            logger.error("[%s] follow %s failed: %s", self.account_name, user_id, e)
            return False

    async def repost(self, tweet_id: str) -> bool:
        self._log("REPOST", tweet_id)
        if self.dry_run:
            return True
        try:
            await self.client.retweet(tweet_id)
            return True
        except Exception as e:
            logger.error("[%s] repost %s failed: %s", self.account_name, tweet_id, e)
            return False

    async def like(self, tweet_id: str) -> bool:
        self._log("LIKE", tweet_id)
        if self.dry_run:
            return True
        try:
            await self.client.favorite_tweet(tweet_id)
            return True
        except Exception as e:
            logger.error("[%s] like %s failed: %s", self.account_name, tweet_id, e)
            return False

    async def reply(self, tweet_id: str, text: str) -> bool:
        self._log("REPLY", tweet_id, f"text={text!r}")
        if self.dry_run:
            return True
        try:
            await self.client.create_tweet(text=text, reply_to=tweet_id)
            return True
        except Exception as e:
            logger.error("[%s] reply to %s failed: %s", self.account_name, tweet_id, e)
            return False

    async def tweet(self, text: str) -> bool:
        self._log("TWEET", "-", f"text={text!r}")
        if self.dry_run:
            return True
        try:
            await self.client.create_tweet(text=text)
            return True
        except Exception as e:
            logger.error("[%s] tweet failed: %s", self.account_name, e)
            return False


TwikitActions = ActionsBase


class SafeRelayActions(ActionsBase):
    def __init__(
        self,
        account_name: str,
        relay_profile: str | None = None,
        dry_run: bool = False,
        client: SafeRelayClient | None = None,
    ):
        profile_name = relay_profile or account_name
        super().__init__(client or create_client_from_env(profile_name), account_name, dry_run)


def create_actions(
    client: Any,
    account_name: str,
    dry_run: bool = False,
    relay_profile: str | None = None,
) -> ActionsBase:
    if isinstance(client, SafeRelayClient):
        return SafeRelayActions(account_name, relay_profile, dry_run, client=client)
    return TwikitActions(client, account_name, dry_run)


def create_safe_relay_actions(
    account_name: str,
    dry_run: bool = False,
    relay_profile: str | None = None,
) -> SafeRelayActions:
    return SafeRelayActions(account_name, relay_profile, dry_run)
