You are implementing an automated Japanese sweepstakes (懸賞) entry tool for X (Twitter).

## Current Direction

twikit has become unstable for X write actions. The preferred implementation
path is to replace the twikit runtime path with
`fa0311/twitter_api_safe_relay` plus a santasan-specific adapter.

For Debian/headless production, prefer the all-in-one Docker Compose stack in
the repository root. It builds Chromium, `twitter_api_safe_relay`, santasan, and
the account-switching entrypoint into one image. The container runs one Chrome
process at a time on `127.0.0.1:9222`, relay connects to that CDP endpoint with
profile `active`, and santasan is invoked as `src/main.py --account <name>`.

Important: `twitter_api_safe_relay` is not a high-level Twitter client. It does
not expose `/follow`, `/like`, `/retweet`, or `/tweet`. It exposes proxy routes
for the X Web App API:

- `GET /health`
- `GET /profiles`
- `GET|POST /i/api/graphql/:queryId/:operationName`
- `GET|POST /1.1/*`
- `GET|POST /2/*`

Select the target account with the `x-profile-name` request header. Never omit
this header in santasan; otherwise the relay may choose a random profile.

## Tech Stack

- `twitter_api_safe_relay` for X Web App API access through logged-in browser profiles
- `twikit` only as the legacy fallback path until the relay adapter is complete
- `evex-dev/rakutenai` for Japanese post/reply generation
- Yahoo! Realtime Search for discovering X posts
- `deepwiki` MCP for investigating upstream repository behavior before changing integration code

## Core Requirements

1. Scrape X posts from Yahoo! Realtime Search using keywords such as
   "フォロー リポスト 懸賞", "RT プレゼント", and "フォロー RT キャンペーン".
2. Classify posts to detect required actions: follow, repost/retweet, like,
   reply, and required hashtags.
3. Preserve multi-account support.
4. In the preferred Debian/headless Safe Relay mode, run one relay profile named
   `active` against one local CDP endpoint (`127.0.0.1:9222`). An external
   orchestrator switches accounts by stopping Chrome, starting Chrome with that
   account's dedicated `--user-data-dir`, restarting relay, and running
   `src/main.py --account <name>`.
5. Each account must use a fully separate browser user-data-dir. Do not run two
   Chrome processes against the same user-data-dir. In active-profile mode,
   relay profile sharing is intentional; browser profile sharing is not.
6. Auto-perform required entry actions with the selected account only.
7. Use rakutenai to generate context-aware Japanese replies and organic posts.
8. Each account should post 2-5 organic tweets per day.
9. Implement reply threads where appropriate.
10. Rate-limit all actions with jitter and backoff.

## Safe Relay Adapter Requirements

Implement the relay integration as an adapter, not as a fake drop-in client with
non-existent high-level routes.

Required adapter behavior:

- Store `relay_url` and `profile_name`.
- Send `x-profile-name: <profile_name>` on every relay request.
- Provide `_graphql_post(query_id, operation_name, variables, features=None)`.
- Provide `_v11_post(path, data)`.
- Keep the existing action method names used by `actions.py`:
  `follow_user`, `retweet`, `favorite_tweet`, and `create_tweet`.

Known action mappings:

| Action | Relay route |
| --- | --- |
| like | `POST /i/api/graphql/lI07N6Otwv1PhnEgXILM7A/FavoriteTweet` |
| repost | `POST /i/api/graphql/ojPdsZsimiJrUGLR1sjUtA/CreateRetweet` |
| tweet/reply | `POST /i/api/graphql/SiM_cAu83R0wnrpmKQQSEw/CreateTweet` |
| follow | `POST /1.1/friendships/create.json` |

The GraphQL query IDs are private X Web App identifiers and may change. Keep
them centralized and easy to update.

Follow needs live validation because twikit used form-encoded data, while the
relay server currently parses v1.1 POST bodies as JSON.

## Multi-Account Session Isolation

The account relationship should not be created by santasan through shared local
state. For the parts this project controls:

- Do not share cookie files, browser profile directories, local storage, or
  Chrome user-data-dir across accounts.
- In the active-profile orchestration mode, multiple santasan accounts all use
  relay profile `active`, but only one account is processed at a time and the
  backing Chrome user-data-dir is swapped by the orchestrator.
- Do not let Safe Relay mode fall back to random relay profile selection.
- Keep per-account rate tracking.
- Keep per-account action logging.

Notes:

- IP address and network-level identity are outside santasan's control.
- Browser-exposed sites do not normally see a device MAC address.
- Do not add browser fingerprint spoofing or detection-evasion logic.

## Rate Limit Rules

- Total actions per account: max 40-50 per hour; 20 per hour for new accounts.
- Posts, replies, and reposts: stay under 50 per 30-minute window; target 2-10
  organic posts per account per day.
- Follows: 5-10 per hour for the first week; configured daily cap applies.
- Likes: max 100/day total across all accounts.
- Reposts: max 50/day total across all accounts.
- Replies: max 30/day total across all accounts.
- Add random delays between actions: 5-30 minutes.
- Distribute actions across a 12-16 hour window.
- Implement exponential backoff on HTTP 429, Error 226, and relay errors.
- Read rate-limit reset headers when available.
- Do not perform all actions at once; queue them with jitter.

## Project Structure

```
project/
├── accounts/
│   └── account_configs.yaml
├── logs/
│   └── actions.log
├── src/
│   ├── search.py          # Yahoo Realtime Search scraper
│   ├── classify.py        # Sweepstakes intent classifier
│   ├── actions.py         # action facade for twikit or Safe Relay adapter
│   ├── safe_relay.py      # Safe Relay adapter
│   ├── generator.py       # RakutenAI prompt wrapper
│   ├── scheduler.py       # rate-limited action queue with jitter
│   ├── account_manager.py # multi-account session/profile loader
│   └── main.py            # entry point
├── SAFE_RELAY_INVESTIGATION.md
├── SAFE_RELAY_SETUP.md
└── config.yaml
```

## Implementation Plan

1. Keep the legacy twikit path working until Safe Relay mode is verified.
2. Add a Safe Relay account-loading path that reads account names and `is_new`
   without instantiating twikit clients.
3. Rewrite `src/safe_relay.py` to use relay-native GraphQL/v1.1 proxy routes.
4. Fix `actions.py` factory logic so Safe Relay actions are properly initialized.
5. Ensure `main.py` passes the selected account/profile name into the relay
   adapter for every action.
6. Verify relay connectivity with `GET /health` and `GET /profiles`.
7. Verify login liveness with `GET /2/users/me` before any real write action.
8. Smoke-test `like`, `repost`, `tweet`, and `reply` with a controlled account.
9. Validate `follow` separately.
10. Only after Safe Relay mode is stable, consider removing twikit from the
   production runtime path.

## Constraints

- All LLM prompts must be in Japanese.
- Do not store plaintext passwords.
- In Safe Relay mode, login state lives in relay-managed browser profiles, not
  santasan cookie files.
- Every action must be logged to `logs/actions.log`.
- Dry-run action logs must not cause production de-duplication skips. Keep
  dry-run logs separate or ignore `DRY_RUN` lines in production checks.
- If a post is older than 24 hours, skip it.
- Skip posts that have already been interacted with.
- Prefer documented upstream behavior from DeepWiki or source inspection before
  changing private X Web API request shapes.
