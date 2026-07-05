import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
_TWIKIT_PATCHED = False


@dataclass
class AccountSession:
    name: str
    client: Any | None
    is_new: bool
    cookie_file: str = ""
    relay_profile: str = ""


def _is_safe_relay_mode() -> bool:
    return (
        os.environ.get("USE_SAFE_RELAY", "").lower() == "true"
        or bool(os.environ.get("RELAY_SERVER_URL"))
    )


def _parse_netscape_cookies(path: str) -> dict[str, str]:
    """Parse a Netscape HTTP Cookie File into a flat {name: value} dict."""
    cookies: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            # columns: domain, include_subdomains, path, secure, expiry, name, value
            name = parts[5]
            value = parts[6]
            cookies[name] = value
    return cookies


def _load_cookies(client: Any, cookie_file: str) -> None:
    """Load cookies from either Netscape format or JSON format."""
    with open(cookie_file, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()

    if first_line.startswith("# Netscape HTTP Cookie File") or first_line == "Netscape HTTP Cookie File":
        cookies = _parse_netscape_cookies(cookie_file)
        client.http.cookies.update(cookies)
        logger.debug("Loaded %d cookies from Netscape file", len(cookies))
    else:
        client.load_cookies(cookie_file)


def _patch_twikit() -> None:
    global _TWIKIT_PATCHED
    if _TWIKIT_PATCHED:
        return

    import bs4
    import httpx as _httpx
    import re as _re
    import twikit.user as _twikit_user
    from twikit.x_client_transaction.transaction import ClientTransaction
    from twikit.x_client_transaction import transaction as _tx

    user_legacy_defaults: dict[str, Any] = {
        "possibly_sensitive": False,
        "can_dm": False,
        "can_media_tag": False,
        "want_retweets": False,
        "has_custom_timelines": False,
        "fast_followers_count": 0,
        "normal_followers_count": 0,
        "media_count": 0,
        "is_translator": False,
        "translator_type": "none",
        "withheld_in_countries": [],
        "pinned_tweet_ids_str": [],
    }

    orig_user_init = _twikit_user.User.__init__

    def safe_user_init(self, client, data, *args, **kwargs):
        legacy = data.get("legacy", {})
        for k, v in user_legacy_defaults.items():
            legacy.setdefault(k, v)
        entities = legacy.setdefault("entities", {})
        entities.setdefault("description", {}).setdefault("urls", [])
        data["legacy"] = legacy
        orig_user_init(self, client, data, *args, **kwargs)

    _twikit_user.User.__init__ = safe_user_init

    on_demand_file_regex = _re.compile(r""",(\d+):["']ondemand\.s["']""")
    on_demand_hash_pattern = r',{}:"([0-9a-f]+)"'
    indices_regex = _re.compile(r"\[(\d+)\],\s*16")
    guest_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    async def guest_get(url: str, ua: str) -> str:
        async with _httpx.AsyncClient(follow_redirects=True, timeout=20) as guest:
            resp = await guest.get(url, headers={"User-Agent": ua, "Accept": "text/html,*/*"})
            return resp.text

    async def get_indices(self, home_page_response, session, headers):
        key_byte_indices: list[str] = []
        response = self.validate_response(home_page_response) or self.home_page_response
        response_str = str(response)
        on_demand_file = on_demand_file_regex.search(response_str)
        if on_demand_file:
            chunk_index = on_demand_file.group(1)
            hash_match = _re.search(on_demand_hash_pattern.format(chunk_index), response_str)
            if hash_match:
                filename = hash_match.group(1)
                url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{filename}a.js"
                ua = (headers or {}).get("User-Agent", guest_ua)
                text = await guest_get(url, ua)
                for item in indices_regex.finditer(text):
                    key_byte_indices.append(item.group(1))
        if not key_byte_indices:
            raise Exception("Couldn't get KEY_BYTE indices")
        key_byte_indices = list(map(int, key_byte_indices))
        return key_byte_indices[0], key_byte_indices[1:]

    async def init(self, session, headers):
        ua = (headers or {}).get("User-Agent", guest_ua)
        html = await guest_get("https://x.com", ua)
        home = bs4.BeautifulSoup(html, "lxml")
        self.home_page_response = self.validate_response(home)
        self.DEFAULT_ROW_INDEX, self.DEFAULT_KEY_BYTES_INDICES = await self.get_indices(
            home, session, headers
        )
        self.key = self.get_key(response=home)
        self.key_bytes = self.get_key_bytes(key=self.key)
        self.animation_key = self.get_animation_key(key_bytes=self.key_bytes, response=home)

    _tx.ON_DEMAND_FILE_REGEX = on_demand_file_regex
    _tx.ON_DEMAND_HASH_PATTERN = on_demand_hash_pattern
    _tx.INDICES_REGEX = indices_regex
    ClientTransaction.get_indices = get_indices
    ClientTransaction.init = init
    _TWIKIT_PATCHED = True


async def load_accounts(
    config_path: str = "accounts/account_configs.yaml",
    *,
    safe_relay: bool | None = None,
) -> list[AccountSession]:
    cfg_path = PROJECT_ROOT / config_path
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if safe_relay is None:
        safe_relay = _is_safe_relay_mode()

    sessions: list[AccountSession] = []
    for acc in cfg.get("accounts", []):
        name = acc["name"]
        is_new = acc.get("is_new", False)

        if safe_relay:
            relay_profile = acc.get("relay_profile", name)
            sessions.append(
                AccountSession(
                    name=name,
                    client=None,
                    is_new=is_new,
                    cookie_file=acc.get("cookie_file", ""),
                    relay_profile=relay_profile,
                )
            )
            logger.info("Loaded Safe Relay profile for account '%s': %s", name, relay_profile)
            continue

        from twikit import Client

        _patch_twikit()
        cookie_file = str(PROJECT_ROOT / acc["cookie_file"])
        if not os.path.exists(cookie_file):
            logger.warning("Cookie file not found for account '%s': %s - skipping", name, cookie_file)
            continue

        client = Client(language="ja-JP")
        try:
            _load_cookies(client, cookie_file)
            logger.info("Loaded cookies for account '%s'", name)
        except Exception as e:
            logger.error("Failed to load cookies for account '%s': %s", name, e)
            continue

        sessions.append(
            AccountSession(
                name=name,
                client=client,
                is_new=is_new,
                cookie_file=cookie_file,
                relay_profile=name,
            )
        )

    if not sessions:
        if safe_relay:
            raise RuntimeError("No Safe Relay account profiles loaded. Check accounts/account_configs.yaml.")
        raise RuntimeError("No valid account sessions loaded. Check cookies/ directory.")

    logger.info("Loaded %d account(s): %s", len(sessions), [s.name for s in sessions])
    return sessions
