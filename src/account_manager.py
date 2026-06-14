import logging
import os
from dataclasses import dataclass
from pathlib import Path

import bs4
import yaml
from twikit import Client
from twikit.x_client_transaction.transaction import ClientTransaction
import twikit.user as _twikit_user

logger = logging.getLogger(__name__)


_USER_LEGACY_DEFAULTS: dict = {
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


def _patch_twikit_user() -> None:
    """
    Monkey-patch twikit.user.User.__init__ to gracefully handle missing keys.
    Bug in twikit v2.3.3: many legacy fields are accessed directly ([key])
    but some user objects returned by the API omit optional fields.
    """
    _orig_user_init = _twikit_user.User.__init__

    def _safe_user_init(self, client, data, *args, **kwargs):
        legacy = data.get('legacy', {})
        # Fill missing optional keys with safe defaults
        for k, v in _USER_LEGACY_DEFAULTS.items():
            legacy.setdefault(k, v)
        # Fix entities.description.urls
        entities = legacy.setdefault('entities', {})
        entities.setdefault('description', {}).setdefault('urls', [])
        data['legacy'] = legacy
        _orig_user_init(self, client, data, *args, **kwargs)

    _twikit_user.User.__init__ = _safe_user_init


_patch_twikit_user()


import re as _re
import httpx as _httpx
from twikit.x_client_transaction import transaction as _tx

# twikit v2.3.3 cannot build a valid X transaction-id, which X now requires on
# its GraphQL API. Two independent breakages, fixed together below:
#
# (1) Wrong regexes. X changed its webpack chunk format (March 2026): 'ondemand.s'
#     is stored as  ,<chunkId>:"ondemand.s"  with the file hash held separately as
#     ,<chunkId>:"<hash>" . The shipped regexes no longer match -> "Couldn't get
#     KEY_BYTE indices". The patterns + get_indices below port the upstream fix
#     from d60/twikit PR #410 (open, unreleased as of 2026-06). See issue #408.
#
# (2) 401 home page. PR #410 alone is NOT enough here: twikit fetches the
#     transaction-id source HTML through the *authenticated* client, which X
#     answers with 401 (empty body), so there is nothing to parse regardless of
#     regex. The home page (and ondemand.s bundle) must be fetched as a *guest*
#     (browser UA, no OAuth bearer / auth-type headers). _init below does that.
#
# Without both fixes the tid is empty/approximated, which was triggering the
# Cloudflare blocks and Error 226 ("request looks automated") seen in the logs.
# See: https://github.com/d60/twikit/issues/408
_ON_DEMAND_FILE_REGEX = _re.compile(r""",(\d+):["']ondemand\.s["']""")
_ON_DEMAND_HASH_PATTERN = r',{}:"([0-9a-f]+)"'
_INDICES_REGEX = _re.compile(r"\[(\d+)\],\s*16")
_GUEST_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _guest_get(url: str, ua: str) -> str:
    """GET a URL as an anonymous browser (no auth headers), return the body text."""
    async with _httpx.AsyncClient(follow_redirects=True, timeout=20) as guest:
        resp = await guest.get(url, headers={"User-Agent": ua, "Accept": "text/html,*/*"})
        return resp.text


def _patch_client_transaction() -> None:
    """Apply d60/twikit PR #410 + guest-home-page fetch to ClientTransaction."""

    async def _get_indices(self, home_page_response, session, headers):
        key_byte_indices: list[str] = []
        response = self.validate_response(home_page_response) or self.home_page_response
        response_str = str(response)
        on_demand_file = _ON_DEMAND_FILE_REGEX.search(response_str)
        if on_demand_file:
            chunk_index = on_demand_file.group(1)
            hash_match = _re.search(
                _ON_DEMAND_HASH_PATTERN.format(chunk_index), response_str
            )
            if hash_match:
                filename = hash_match.group(1)
                url = (
                    "https://abs.twimg.com/responsive-web/client-web/"
                    f"ondemand.s.{filename}a.js"
                )
                ua = (headers or {}).get("User-Agent", _GUEST_UA)
                text = await _guest_get(url, ua)
                for item in _INDICES_REGEX.finditer(text):
                    key_byte_indices.append(item.group(1))
        if not key_byte_indices:
            raise Exception("Couldn't get KEY_BYTE indices")
        key_byte_indices = list(map(int, key_byte_indices))
        return key_byte_indices[0], key_byte_indices[1:]

    async def _init(self, session, headers):
        ua = (headers or {}).get("User-Agent", _GUEST_UA)
        html = await _guest_get("https://x.com", ua)
        home = bs4.BeautifulSoup(html, "lxml")
        self.home_page_response = self.validate_response(home)
        self.DEFAULT_ROW_INDEX, self.DEFAULT_KEY_BYTES_INDICES = await self.get_indices(
            home, session, headers
        )
        self.key = self.get_key(response=home)
        self.key_bytes = self.get_key_bytes(key=self.key)
        self.animation_key = self.get_animation_key(
            key_bytes=self.key_bytes, response=home
        )

    # Replace the module-level regexes so any internal references use the new format.
    _tx.ON_DEMAND_FILE_REGEX = _ON_DEMAND_FILE_REGEX
    _tx.ON_DEMAND_HASH_PATTERN = _ON_DEMAND_HASH_PATTERN
    _tx.INDICES_REGEX = _INDICES_REGEX
    ClientTransaction.get_indices = _get_indices
    ClientTransaction.init = _init


_patch_client_transaction()

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class AccountSession:
    name: str
    client: Client
    is_new: bool
    cookie_file: str


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


def _load_cookies(client: Client, cookie_file: str) -> None:
    """Load cookies from either Netscape format or JSON format."""
    with open(cookie_file, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()

    if first_line.startswith("# Netscape HTTP Cookie File") or first_line == "Netscape HTTP Cookie File":
        cookies = _parse_netscape_cookies(cookie_file)
        client.http.cookies.update(cookies)
        logger.debug("Loaded %d cookies from Netscape file", len(cookies))
    else:
        # Assume JSON format
        client.load_cookies(cookie_file)


async def load_accounts(config_path: str = "accounts/account_configs.yaml") -> list[AccountSession]:
    cfg_path = PROJECT_ROOT / config_path
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    sessions: list[AccountSession] = []
    for acc in cfg.get("accounts", []):
        name = acc["name"]
        cookie_file = str(PROJECT_ROOT / acc["cookie_file"])
        is_new = acc.get("is_new", False)

        if not os.path.exists(cookie_file):
            logger.warning("Cookie file not found for account '%s': %s — skipping", name, cookie_file)
            continue

        client = Client(language="ja-JP")
        try:
            _load_cookies(client, cookie_file)
            logger.info("Loaded cookies for account '%s'", name)
        except Exception as e:
            logger.error("Failed to load cookies for account '%s': %s", name, e)
            continue

        sessions.append(AccountSession(name=name, client=client, is_new=is_new, cookie_file=cookie_file))

    if not sessions:
        raise RuntimeError("No valid account sessions loaded. Check cookies/ directory.")

    logger.info("Loaded %d account(s): %s", len(sessions), [s.name for s in sessions])
    return sessions
