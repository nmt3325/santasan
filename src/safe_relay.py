"""
Safe Relay adapter for twitter_api_safe_relay.

twitter_api_safe_relay is a browser-backed proxy for X Web App API routes. It
does not expose high-level routes such as /follow or /tweet, so this adapter
keeps the small twikit-like method surface used by actions.py and translates it
to relay-native GraphQL/v1.1 requests.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


CREATE_TWEET_QUERY_ID = "SiM_cAu83R0wnrpmKQQSEw"
CREATE_TWEET_OPERATION = "CreateTweet"
FAVORITE_TWEET_QUERY_ID = "lI07N6Otwv1PhnEgXILM7A"
FAVORITE_TWEET_OPERATION = "FavoriteTweet"
CREATE_RETWEET_QUERY_ID = "ojPdsZsimiJrUGLR1sjUtA"
CREATE_RETWEET_OPERATION = "CreateRetweet"


# Copied from twikit 2.3.3's default FEATURES for CreateTweet. These are private
# X Web App switches and may need updating when X changes its web client.
DEFAULT_TWEET_FEATURES: dict[str, Any] = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


FOLLOW_DATA_DEFAULTS: dict[str, int] = {
    "include_profile_interstitial_type": 1,
    "include_blocking": 1,
    "include_blocked_by": 1,
    "include_followed_by": 1,
    "include_want_retweets": 1,
    "include_mute_edge": 1,
    "include_can_dm": 1,
    "include_can_media_tag": 1,
    "include_ext_is_blue_verified": 1,
    "include_ext_verified_type": 1,
    "include_ext_profile_image_shape": 1,
    "skip_status": 1,
}


@dataclass(slots=True)
class SafeRelayClient:
    relay_url: str
    profile_name: str
    api_key: str | None = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.relay_url = self.relay_url.rstrip("/")
        if not self.relay_url:
            raise RuntimeError("relay_url is required")
        if not self.profile_name:
            raise RuntimeError("profile_name is required")

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "x-profile-name": self.profile_name,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url_path = path if path.startswith("/") else f"/{path}"
        async with httpx.AsyncClient(
            base_url=self.relay_url,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        ) as client:
            try:
                response = await client.request(
                    method,
                    url_path,
                    json=json_data,
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500]
                logger.error(
                    "[%s] relay %s %s failed: HTTP %s %s",
                    self.profile_name,
                    method,
                    url_path,
                    e.response.status_code,
                    body,
                )
                raise RuntimeError(
                    f"Relay server error for {method} {url_path}: "
                    f"HTTP {e.response.status_code}: {body}"
                ) from e
            except httpx.RequestError as e:
                logger.error(
                    "[%s] relay %s %s connection failed: %s",
                    self.profile_name,
                    method,
                    url_path,
                    e,
                )
                raise RuntimeError(f"Relay connection error for {method} {url_path}: {e}") from e

        try:
            result = response.json()
        except ValueError as e:
            raise RuntimeError(
                f"Relay returned non-JSON response for {method} {url_path}: "
                f"{response.text[:500]}"
            ) from e

        logger.debug("[%s] relay %s %s ok", self.profile_name, method, url_path)
        return result

    async def _graphql_post(
        self,
        query_id: str,
        operation_name: str,
        variables: dict[str, Any],
        features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "variables": variables,
            "queryId": query_id,
        }
        if features is not None:
            body["features"] = features

        return await self._request(
            "POST",
            f"/i/api/graphql/{query_id}/{operation_name}",
            json_data=body,
        )

    async def _v11_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if not path.startswith("/1.1/"):
            raise ValueError(f"v1.1 relay path must start with /1.1/: {path}")
        return await self._request("POST", path, json_data=data)

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def profiles(self) -> dict[str, Any]:
        return await self._request("GET", "/profiles")

    async def current_user(self) -> dict[str, Any]:
        return await self._request("GET", "/2/users/me")

    async def assert_login_alive(self) -> dict[str, Any]:
        try:
            return await self.current_user()
        except RuntimeError as e:
            raise RuntimeError(
                f"Safe Relay profile '{self.profile_name}' is not logged in or "
                f"cannot use X Web API. Re-login the active Chrome profile. {e}"
            ) from e

    async def follow_user(self, user_id: str) -> dict[str, Any]:
        data = dict(FOLLOW_DATA_DEFAULTS)
        data["user_id"] = user_id
        return await self._v11_post("/1.1/friendships/create.json", data)

    async def retweet(self, tweet_id: str) -> dict[str, Any]:
        return await self._graphql_post(
            CREATE_RETWEET_QUERY_ID,
            CREATE_RETWEET_OPERATION,
            {"tweet_id": tweet_id, "dark_request": False},
        )

    async def favorite_tweet(self, tweet_id: str) -> dict[str, Any]:
        return await self._graphql_post(
            FAVORITE_TWEET_QUERY_ID,
            FAVORITE_TWEET_OPERATION,
            {"tweet_id": tweet_id},
        )

    async def create_tweet(
        self,
        text: str,
        reply_to: str | None = None,
        media_ids: list[str] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": [
                    {"media_id": media_id, "tagged_users": []}
                    for media_id in (media_ids or [])
                ],
                "possibly_sensitive": False,
            },
            "semantic_annotation_ids": [],
        }

        if reply_to is not None:
            variables["reply"] = {
                "in_reply_to_tweet_id": reply_to,
                "exclude_reply_user_ids": [],
            }

        return await self._graphql_post(
            CREATE_TWEET_QUERY_ID,
            CREATE_TWEET_OPERATION,
            variables,
            DEFAULT_TWEET_FEATURES,
        )


def create_client_from_env(profile_name: str | None = None) -> SafeRelayClient:
    relay_url = os.environ.get("RELAY_SERVER_URL", "").strip()
    if not relay_url:
        raise RuntimeError(
            "RELAY_SERVER_URL is required. Example: "
            "RELAY_SERVER_URL=http://localhost:3000"
        )

    selected_profile = (
        profile_name
        or os.environ.get("RELAY_PROFILE_NAME")
        or os.environ.get("RELAY_ACCOUNT_ID")
        or ""
    ).strip()
    if not selected_profile:
        raise RuntimeError(
            "Safe Relay profile name is required. Pass the account/session name "
            "or set RELAY_PROFILE_NAME."
        )

    timeout_str = os.environ.get("RELAY_TIMEOUT", "30")
    try:
        timeout = float(timeout_str)
    except ValueError as e:
        raise RuntimeError(f"Invalid RELAY_TIMEOUT value: {timeout_str}") from e

    return SafeRelayClient(
        relay_url=relay_url,
        profile_name=selected_profile,
        api_key=os.environ.get("RELAY_API_KEY"),
        timeout=timeout,
    )


async def check_cdp_version(cdp_url: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    """Check a Chrome DevTools Protocol endpoint if one is configured."""
    selected_url = (
        cdp_url
        or os.environ.get("CDP_VERSION_URL")
        or os.environ.get("CDP_ENDPOINT_URL")
        or os.environ.get("CDP_ENDPOINT")
        or os.environ.get("CHROME_CDP_URL")
        or ""
    ).strip()
    if not selected_url:
        raise RuntimeError(
            "CDP endpoint is not configured. Set CDP_ENDPOINT_URL=http://127.0.0.1:9222"
        )

    selected_url = selected_url.rstrip("/")
    version_url = (
        selected_url
        if selected_url.endswith("/json/version")
        else f"{selected_url}/json/version"
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        response = await client.get(version_url)
        response.raise_for_status()
        return response.json()
