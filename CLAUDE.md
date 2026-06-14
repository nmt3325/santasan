You are implementing an automated Japanese sweepstakes (懸賞) entry tool for X (Twitter).

## Tech Stack
- `twikit` (https://github.com/d60/twikit) for X account automation (no API key, cookie-based login)
- `evex-dev/rakutenai` (https://github.com/evex-dev/rakutenai) for LLM-based post/reply generation
- Yahoo! Realtime Search (https://search.yahoo.co.jp/realtime) for scraping X posts. specifications are listed here(https://qiita.com/maebahesioru/items/4fc4e6baf5b96aa8406)
- Use `deepwiki` MCP to investigate detailed usage of twikit and rakutenai before writing code

## Core Requirements
1. Scrape X posts from Yahoo! Realtime Search using keywords like "フォロー リポスト 懸賞", "RT プレゼント", "フォロー RT キャンペーン"
2. Classify posts to detect required actions (follow, repost/retweet, like, reply, hashtag)
3. Support multiple X accounts managed via twikit with cookie-based sessions
4. Auto-perform required entry actions (follow, repost, like, reply) using the correct account
5. Use rakutenai to generate human-like, context-aware replies and posts in Japanese
6. Each account must post 2-5 organic tweets per day to avoid bot detection
7. Implement reply threads to appear more human-like
8. Rate-limit all actions to stay within X's velocity-based detection thresholds

## Rate Limit & Anti-Bot Rules (Strict)
- Total actions per account: max 40-50 per hour, 20 per hour for new accounts
- Posts (tweets + replies + reposts): max 2,400/day, but stay under 50 per 30-minute window; target 2-10 per day
- Follows: 5-10 per hour for the first week, max 400/day (free) or 1,000/day (Premium)
- Likes: max 100/day total across all accounts
- Reposts: max 50/day total across all accounts
- Replies: max 30/day total across all accounts
- Add random delays between actions: 5-30 minutes
- Distribute actions across a 12-16 hour window
- Implement exponential backoff (1, 2, 4, 8... minutes) on HTTP 429 or Error 226
- Read `x-rate-limit-reset` headers and pause until reset time when rate limited
- Never use a VPN for X sessions; it increases Error 226 risk
- Do not perform all actions at once; queue them with jitter

## Project Structure
```
project/
├── accounts/
│   └── account_configs.yaml
├── cookies/
│   └── {account_name}.json
├── logs/
│   └── actions.log
├── src/
│   ├── search.py         # Yahoo Realtime Search scraper
│   ├── classify.py       # Sweepstakes intent classifier
│   ├── actions.py        # Twikit wrapper (follow, repost, reply, tweet)
│   ├── generator.py      # RakutenAI prompt wrapper
│   ├── scheduler.py      # Rate-limited action queue with jitter
│   ├── account_manager.py# Multi-account session loader
│   └── main.py           # Entry point
└── config.yaml
```

## Implementation Steps
1. Use `deepwiki` MCP to fetch detailed documentation for twikit and rakutenai APIs
2. Build Yahoo Realtime Search scraper using `https://search.yahoo.co.jp/realtime/api/v1/pagination?p={keyword}&results=40`
3. First, run a discovery pass: fetch 100 posts with the sweepstakes keywords, print them, and propose classification rules before implementing the auto-entry logic
4. Build the account manager with cookie-based login for each account
5. Implement the action engine with hard rate-limit guards
6. Integrate rakutenai for generating organic daily posts and contextual replies
7. Add logging for every action with timestamp and account name
8. Create a dry-run mode that simulates actions without executing them

## Constraints
- All LLM prompts must be in Japanese
- Do not store plaintext passwords; use cookies only
- Every action must be logged to `logs/actions.log`
- If a post is older than 24 hours, skip it
- Skip posts that have already been interacted with (check logs)
```