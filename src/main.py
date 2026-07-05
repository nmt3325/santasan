#!/usr/bin/env python3
"""
santasan — automated Japanese sweepstakes entry tool for X (Twitter).

Usage:
  python src/main.py              # normal run
  python src/main.py --dry-run    # simulate without executing
  python src/main.py --discover   # fetch & print tweets, then exit
"""

import argparse
import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from account_manager import load_accounts, AccountSession
from actions import create_safe_relay_actions, TwikitActions
from classify import classify
from generator import generate_organic_tweet, generate_reply
from scheduler import (
    RateLimitConfig,
    AccountRateTracker,
    GlobalRateTracker,
    jitter_delay,
    run_with_backoff,
)
from search import discover, fetch_tweets
from safe_relay import create_client_from_env


def setup_logging(log_file: str, dry_run: bool) -> None:
    log_path = PROJECT_ROOT / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    level = logging.DEBUG if dry_run else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        handlers=handlers,
    )


def load_config(path: str = "config.yaml") -> dict:
    with open(PROJECT_ROOT / path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def already_interacted(tweet_id: str, log_file: Path) -> bool:
    if not log_file.exists():
        return False
    try:
        content = log_file.read_text(encoding="utf-8")
        return f"target={tweet_id}" in content
    except OSError:
        return False


def is_safe_relay_mode() -> bool:
    return (
        os.environ.get("USE_SAFE_RELAY", "").lower() == "true"
        or bool(os.environ.get("RELAY_SERVER_URL"))
    )


def get_actions(session: AccountSession, dry_run: bool):
    """Get the appropriate actions handler based on configuration."""
    if is_safe_relay_mode():
        return create_safe_relay_actions(
            session.name,
            dry_run=dry_run,
            relay_profile=session.relay_profile or session.name,
        )
    return TwikitActions(session.client, session.name, dry_run=dry_run)


async def verify_safe_relay_profiles(sessions: list[AccountSession]) -> None:
    if not sessions:
        return

    first_profile = sessions[0].relay_profile or sessions[0].name
    client = create_client_from_env(first_profile)
    profiles_resp = await client.profiles()
    available = set(profiles_resp.get("profiles", []))
    required = {s.relay_profile or s.name for s in sessions}
    missing = sorted(required - available)
    if missing:
        raise RuntimeError(
            "Safe Relay profiles missing: "
            f"{missing}. Available profiles: {sorted(available)}"
        )
    logging.info("Safe Relay profiles verified: %s", sorted(required))


async def run_sweepstakes_entry(
    tweet: dict,
    session: AccountSession,
    tracker: AccountRateTracker,
    global_tracker: GlobalRateTracker,
    cfg: dict,
    dry_run: bool,
    log_path: Path,
) -> None:
    if already_interacted(tweet["id"], log_path):
        logging.debug("Already interacted with tweet %s — skipping", tweet["id"])
        return

    req = classify(tweet["text"])
    if not req.is_sweepstakes:
        logging.debug("Tweet %s not classified as sweepstakes — skipping", tweet["id"])
        return

    actor = get_actions(session, dry_run)
    gen_cfg = cfg.get("generator", {})
    node_script = gen_cfg.get("node_script", "generator_node/generate.mjs")
    gen_timeout = float(gen_cfg.get("timeout_seconds", 30))

    logging.info(
        "[%s] Entering sweepstakes tweet %s | follow=%s repost=%s like=%s reply=%s",
        session.name, tweet["id"], req.follow, req.repost, req.like, req.reply,
    )

    if req.follow and tracker.can_follow() and tracker.can_act():
        user_id = tweet.get("user_id", "")
        if user_id:
            ok = await run_with_backoff(lambda: actor.follow(user_id), tracker)
            if ok:
                tracker.record_action("follow")
            await jitter_delay(RateLimitConfig.from_dict(cfg))

    if req.repost and global_tracker.can_repost() and tracker.can_act():
        ok = await run_with_backoff(lambda: actor.repost(tweet["id"]), tracker)
        if ok:
            tracker.record_action("repost")
            global_tracker.record_repost()
        await jitter_delay(RateLimitConfig.from_dict(cfg))

    if req.like and global_tracker.can_like() and tracker.can_act():
        ok = await run_with_backoff(lambda: actor.like(tweet["id"]), tracker)
        if ok:
            tracker.record_action("like")
            global_tracker.record_like()
        await jitter_delay(RateLimitConfig.from_dict(cfg))

    if req.reply and global_tracker.can_reply() and tracker.can_act():
        reply_text = await generate_reply(
            tweet_text=tweet["text"],
            hashtags=req.hashtags,
            node_script=node_script,
            timeout=gen_timeout,
        )
        ok = await run_with_backoff(lambda: actor.reply(tweet["id"], reply_text), tracker)
        if ok:
            tracker.record_action("reply")
            global_tracker.record_reply()
        await jitter_delay(RateLimitConfig.from_dict(cfg))


async def post_organic_tweets(
    session: AccountSession,
    tracker: AccountRateTracker,
    cfg: dict,
    dry_run: bool,
) -> None:
    rl = cfg.get("rate_limits", {})
    min_tweets = rl.get("organic_tweets_per_day_min", 2)
    max_tweets = rl.get("organic_tweets_per_day_max", 5)
    count = random.randint(min_tweets, max_tweets)

    gen_cfg = cfg.get("generator", {})
    node_script = gen_cfg.get("node_script", "generator_node/generate.mjs")
    gen_timeout = float(gen_cfg.get("timeout_seconds", 30))

    actor = get_actions(session, dry_run)
    rl_cfg = RateLimitConfig.from_dict(cfg)

    for i in range(count):
        if not tracker.can_act():
            logging.warning("[%s] Hourly limit hit, skipping organic tweet %d/%d", session.name, i+1, count)
            break
        text = await generate_organic_tweet(node_script=node_script, timeout=gen_timeout)
        ok = await run_with_backoff(lambda: actor.tweet(text), tracker)
        if ok:
            tracker.record_action("tweet")
        if i < count - 1:
            await jitter_delay(rl_cfg)


async def main_loop(cfg: dict, dry_run: bool, run_once: bool = False) -> None:
    log_path = PROJECT_ROOT / cfg.get("log_file", "logs/actions.log")
    keywords: list[str] = cfg.get("keywords", [])
    search_cfg = cfg.get("search", {})
    results_per_query = search_cfg.get("results_per_query", 40)
    max_age_hours = search_cfg.get("max_age_hours", 24)
    rl_cfg = RateLimitConfig.from_dict(cfg)

    safe_relay = is_safe_relay_mode()
    sessions = await load_accounts(safe_relay=safe_relay)
    if safe_relay and not dry_run:
        await verify_safe_relay_profiles(sessions)
    global_tracker = GlobalRateTracker(rl_cfg)
    account_trackers = {
        s.name: AccountRateTracker(s.name, s.is_new, rl_cfg)
        for s in sessions
    }

    logging.info(
        "Starting santasan | accounts=%s mode=%s dry_run=%s",
        [s.name for s in sessions],
        "safe_relay" if safe_relay else "twikit",
        dry_run,
    )

    while True:
        all_tweets: list[dict] = []
        seen_ids: set[str] = set()
        for keyword in keywords:
            tweets = await fetch_tweets(keyword, results=results_per_query, max_age_hours=max_age_hours)
            for t in tweets:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    all_tweets.append(t)

        random.shuffle(all_tweets)
        logging.info("Collected %d unique sweepstakes candidates", len(all_tweets))

        for session in sessions:
            tracker = account_trackers[session.name]
            await post_organic_tweets(session, tracker, cfg, dry_run)

        for tweet in all_tweets:
            session = random.choice(sessions)
            tracker = account_trackers[session.name]
            await tracker.consume_backoff()
            if not tracker.can_act():
                logging.info("[%s] Hourly limit reached, pausing...", session.name)
                await asyncio.sleep(300)
                continue
            await run_sweepstakes_entry(tweet, session, tracker, global_tracker, cfg, dry_run, log_path)

        if run_once:
            logging.info("Cycle complete. --once set, exiting.")
            return

        logging.info("Cycle complete. Sleeping 30 minutes before next search...")
        await asyncio.sleep(1800)


async def main() -> None:
    parser = argparse.ArgumentParser(description="santasan — automated sweepstakes entry tool")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without executing")
    parser.add_argument("--discover", action="store_true", help="Fetch and print tweets, then exit")
    parser.add_argument("--once", action="store_true", help="Run one cycle, then exit")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dry_run = args.dry_run or cfg.get("dry_run", False)
    setup_logging(cfg.get("log_file", "logs/actions.log"), dry_run)

    if args.discover:
        keywords = cfg.get("keywords", [])
        results = cfg.get("search", {}).get("results_per_query", 40)
        tweets = await discover(keywords, results=results)
        print(f"\n=== DISCOVERY COMPLETE: {len(tweets)} unique tweets ===")
        print("\nProposed classification rules based on samples above:")
        print("  - 'フォロー' → follow the posting account")
        print("  - 'RT' / 'リポスト' / 'リツイート' → repost the tweet")
        print("  - 'いいね' / '♥' → like the tweet")
        print("  - 'リプライ' / 'コメント' / '返信' → reply to the tweet")
        print("  - '#タグ' in tweet text → include hashtag in reply")
        print("\nRun without --discover to start auto-entry.")
        return

    if dry_run:
        logging.info("DRY-RUN MODE: no real actions will be performed")

    await main_loop(cfg, dry_run, run_once=args.once)


if __name__ == "__main__":
    asyncio.run(main())
