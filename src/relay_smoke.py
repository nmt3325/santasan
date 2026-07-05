#!/usr/bin/env python3
"""
Single-action Safe Relay smoke test.

This script is intentionally separate from main.py so live testing can be done
one action at a time against a controlled profile/tweet.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from safe_relay import create_client_from_env


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Safe Relay action")
    parser.add_argument("--profile", required=True, help="Relay profile name")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the action. Omit for dry-run only.",
    )

    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("profiles")

    tweet = sub.add_parser("tweet")
    tweet.add_argument("text")

    reply = sub.add_parser("reply")
    reply.add_argument("tweet_id")
    reply.add_argument("text")

    like = sub.add_parser("like")
    like.add_argument("tweet_id")

    repost = sub.add_parser("repost")
    repost.add_argument("tweet_id")

    follow = sub.add_parser("follow")
    follow.add_argument("user_id")

    args = parser.parse_args()

    if not os.environ.get("RELAY_SERVER_URL"):
        raise SystemExit("RELAY_SERVER_URL is required, e.g. http://localhost:3000")

    client = create_client_from_env(args.profile)

    if args.action == "profiles":
        print(await client.profiles())
        return

    print(f"profile={args.profile} action={args.action} execute={args.execute}")
    if not args.execute:
        print("DRY_RUN: add --execute to perform the action")
        return

    if args.action == "tweet":
        print(await client.create_tweet(args.text))
    elif args.action == "reply":
        print(await client.create_tweet(args.text, reply_to=args.tweet_id))
    elif args.action == "like":
        print(await client.favorite_tweet(args.tweet_id))
    elif args.action == "repost":
        print(await client.retweet(args.tweet_id))
    elif args.action == "follow":
        print(await client.follow_user(args.user_id))


if __name__ == "__main__":
    asyncio.run(main())
