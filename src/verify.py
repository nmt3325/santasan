#!/usr/bin/env python3
"""
verify.py — non-destructive health check for santasan.

Confirms the major subsystems work for BOTH accounts without performing
any irreversible write actions (no follow/like/repost/tweet). Specifically:
  1. Cookie loading + authenticated session for each account (read-only).
  2. Yahoo Realtime Search scraping.
  3. Sweepstakes classification.
  4. Reply / organic-tweet generation (text only, not posted).

Usage:
  python src/verify.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from urllib.parse import unquote

from safe_relay import create_client_from_env
from account_manager import load_accounts, _parse_netscape_cookies
from classify import classify
from generator import generate_organic_tweet, generate_reply
from search import fetch_tweets
from main import load_config
from main import is_safe_relay_mode


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


async def check_accounts() -> bool:
    if is_safe_relay_mode():
        print("\n[1/4] Safe Relay profiles (read-only)")
        sessions = await load_accounts(safe_relay=True)
        all_ok = True
        for s in sessions:
            profile = s.relay_profile or s.name
            try:
                client = create_client_from_env(profile)
                health = await client.health()
                profiles_resp = await client.profiles()
                profiles = profiles_resp.get("profiles", [])
                if profile in profiles:
                    ok(f"{s.name}: relay profile '{profile}' available "
                       f"(health={health.get('status')})")
                else:
                    fail(f"{s.name}: relay profile '{profile}' missing; available={profiles}")
                    all_ok = False
            except Exception as e:
                fail(f"{s.name}: relay check FAILED — {type(e).__name__}: {e}")
                all_ok = False
        return all_ok

    print("\n[1/4] Account authentication (read-only)")
    sessions = await load_accounts(safe_relay=False)
    all_ok = True
    for s in sessions:
        # Derive own user-id from the twid cookie (u%3D<id>), then do a
        # read-only authenticated lookup. client.user() is unreliable with
        # the transaction-id fallback, so we look ourselves up by id.
        try:
            cookies = _parse_netscape_cookies(s.cookie_file)
        except Exception:
            cookies = {}
        twid = unquote(cookies.get("twid", ""))  # e.g. "u=2065969742033362944"
        own_id = twid.split("=", 1)[1] if "=" in twid else ""
        has_auth = bool(cookies.get("auth_token")) and bool(cookies.get("ct0"))

        if not has_auth:
            fail(f"{s.name}: missing auth_token/ct0 in cookie file")
            all_ok = False
            continue
        if not own_id:
            fail(f"{s.name}: no twid (user id) in cookie file — cannot verify")
            all_ok = False
            continue

        # Use the legacy v1.1 verify_credentials endpoint: it needs only the
        # auth_token + ct0 cookies (no GraphQL transaction-id), so it is not
        # blocked by the Cloudflare challenge that breaks the read GraphQL API.
        try:
            resp = await s.client.http.get(
                "https://api.x.com/1.1/account/verify_credentials.json",
                headers={
                    "authorization": "Bearer "
                    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
                    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
                    "x-csrf-token": cookies.get("ct0", ""),
                },
            )
            if resp.status_code == 200:
                j = resp.json()
                ok(f"{s.name}: authenticated as @{j.get('screen_name')} "
                   f"(id={j.get('id_str')}, followers={j.get('followers_count')}, "
                   f"new={s.is_new})")
            else:
                fail(f"{s.name}: verify_credentials HTTP {resp.status_code} "
                     f"— {resp.text[:120]!r}")
                all_ok = False
        except Exception as e:
            fail(f"{s.name}: lookup FAILED (id={own_id}) — {type(e).__name__}: {e}")
            all_ok = False
    return all_ok


async def check_search(cfg: dict) -> list[dict]:
    print("\n[2/4] Yahoo Realtime Search scraping")
    keywords = cfg.get("keywords", [])
    results = cfg.get("search", {}).get("results_per_query", 40)
    max_age = cfg.get("search", {}).get("max_age_hours", 24)
    tweets: list[dict] = []
    try:
        kw = keywords[0]
        tweets = await fetch_tweets(kw, results=results, max_age_hours=max_age)
        if tweets:
            ok(f"fetched {len(tweets)} tweets for '{kw}'")
        else:
            fail(f"fetched 0 tweets for '{kw}' (search may be rate-limited)")
    except Exception as e:
        fail(f"search FAILED — {type(e).__name__}: {e}")
    return tweets


def check_classify(tweets: list[dict]) -> None:
    print("\n[3/4] Sweepstakes classification")
    if not tweets:
        fail("no tweets available to classify (skipped)")
        return
    hits = 0
    for t in tweets:
        req = classify(t["text"])
        if req.is_sweepstakes:
            hits += 1
    ok(f"classified {len(tweets)} tweets — {hits} matched as sweepstakes "
       f"(follow/repost/like/reply flags resolved)")


async def check_generator(cfg: dict, tweets: list[dict]) -> None:
    print("\n[4/4] Text generation (RakutenAI, not posted)")
    gen_cfg = cfg.get("generator", {})
    node_script = gen_cfg.get("node_script", "generator_node/generate.mjs")
    timeout = float(gen_cfg.get("timeout_seconds", 30))
    try:
        text = await generate_organic_tweet(node_script=node_script, timeout=timeout)
        if text and text.strip():
            ok(f"organic tweet generated: {text[:60]!r}...")
        else:
            fail("organic tweet generation returned empty text")
    except Exception as e:
        fail(f"organic generation FAILED — {type(e).__name__}: {e}")

    try:
        sample = tweets[0]["text"] if tweets else "フォロー&RTで当たる！プレゼントキャンペーン #懸賞"
        reply = await generate_reply(tweet_text=sample, hashtags=[],
                                     node_script=node_script, timeout=timeout)
        if reply and reply.strip():
            ok(f"reply generated: {reply[:60]!r}...")
        else:
            fail("reply generation returned empty text")
    except Exception as e:
        fail(f"reply generation FAILED — {type(e).__name__}: {e}")


async def main() -> None:
    cfg = load_config()
    print("=" * 60)
    print("santasan — production health check (non-destructive)")
    print("=" * 60)

    accounts_ok = await check_accounts()
    tweets = await check_search(cfg)
    check_classify(tweets)
    await check_generator(cfg, tweets)

    print("\n" + "=" * 60)
    if accounts_ok:
        print("RESULT: accounts authenticated OK. See per-check marks above.")
    else:
        print("RESULT: one or more accounts FAILED authentication — fix cookies.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
