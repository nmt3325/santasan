import re
import httpx
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

SEARCH_API = "https://search.yahoo.co.jp/realtime/api/v1/pagination"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://search.yahoo.co.jp/realtime",
    "X-Requested-With": "XMLHttpRequest",
}

# Yahoo wraps matched keywords with \tSTART\t...\tEND\t markers
_HIGHLIGHT_RE = re.compile(r"\tSTART\t|\tEND\t")


def _clean_text(text: str) -> str:
    return _HIGHLIGHT_RE.sub("", text).strip()


def _normalize_tweet(raw: dict) -> dict | None:
    tweet_id = raw.get("id")
    # displayText contains the full tweet body with highlight markers
    raw_text = raw.get("displayText") or raw.get("displayTextBody") or ""
    text = _clean_text(raw_text)
    user_id = raw.get("userId", "")
    screen_name = raw.get("screenName") or raw.get("name") or ""
    created_at_ts = raw.get("createdAt")
    created_at = datetime.fromtimestamp(created_at_ts, tz=timezone.utc) if created_at_ts else None
    hashtags = raw.get("hashtags") or []

    if not tweet_id or not text:
        return None

    return {
        "id": str(tweet_id),
        "text": text,
        "user_id": str(user_id),
        "screen_name": screen_name,
        "created_at": created_at,
        "hashtags": hashtags,
        "url": raw.get("url", ""),
    }


async def fetch_tweets(keyword: str, results: int = 40, max_age_hours: int = 24) -> list[dict]:
    params = {"p": keyword, "results": results}
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)

    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(SEARCH_API, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("Yahoo search HTTP error %s for keyword '%s'", e.response.status_code, keyword)
            return []
        except httpx.RequestError as e:
            logger.error("Yahoo search request error for keyword '%s': %s", keyword, e)
            return []

        try:
            data = resp.json()
        except Exception:
            logger.error("Yahoo search returned non-JSON for keyword '%s'", keyword)
            logger.debug("Raw response: %s", resp.text[:500])
            return []

    raw_entries = data.get("timeline", {}).get("entry", [])
    tweets = []
    for raw in raw_entries:
        t = _normalize_tweet(raw)
        if t is None:
            continue
        if t["created_at"] and t["created_at"] < cutoff:
            logger.debug("Skipping old tweet %s (created %s)", t["id"], t["created_at"])
            continue
        tweets.append(t)

    logger.info("Keyword '%s': fetched %d tweets (%d raw)", keyword, len(tweets), len(raw_entries))
    return tweets


async def discover(keywords: list[str], results: int = 40) -> list[dict]:
    """Discovery pass: fetch tweets per keyword and print samples."""
    all_tweets: list[dict] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        for keyword in keywords:
            print(f"\n{'='*60}")
            print(f"KEYWORD: {keyword}")
            print(f"{'='*60}")
            params = {"p": keyword, "results": results}
            try:
                resp = await client.get(SEARCH_API, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"ERROR: {e}")
                continue

            raw_entries = data.get("timeline", {}).get("entry", [])
            total = data.get("timeline", {}).get("head", {}).get("totalResultsAvailable", 0)
            print(f"Found {len(raw_entries)} entries (total available: {total}). Sample (first 3):")
            for i, raw in enumerate(raw_entries[:3]):
                t = _normalize_tweet(raw)
                if t:
                    print(f"\n--- Tweet {i+1} ---")
                    print(f"  id         : {t['id']}")
                    print(f"  screen_name: @{t['screen_name']}")
                    print(f"  text       : {t['text'][:120]}")
                    print(f"  created_at : {t['created_at']}")
                    print(f"  url        : {t['url']}")

            for raw in raw_entries:
                t = _normalize_tweet(raw)
                if t and t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    all_tweets.append(t)

    print(f"\n{'='*60}")
    print(f"TOTAL UNIQUE TWEETS: {len(all_tweets)}")
    return all_tweets
