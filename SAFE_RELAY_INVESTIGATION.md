# twitter_api_safe_relay implementation investigation

Date: 2026-07-05

## Conclusion

`fa0311/twitter_api_safe_relay` can replace the fragile parts of the current
twikit-based X access, but it is not a high-level Twitter client. It is a
browser-backed HTTP relay for X Web App API requests.

The viable replacement is:

1. Run `twitter_api_safe_relay` with logged-in browser profiles.
2. Replace twikit action calls with a small adapter that sends the same
   GraphQL/v1.1 request shapes through the relay.
3. Select the target account by sending `x-profile-name: <account name>`.

The current `src/safe_relay.py` is not compatible with the actual relay API
because it calls non-existent high-level routes such as `/follow`, `/retweet`,
`/like`, and `/tweet`.

## Verified relay behavior

From `packages/server/src/app.ts` in `fa0311/twitter_api_safe_relay`:

- `GET /health`
- `GET /profiles`
- `GET /i/api/graphql/:queryId/:operationName`
- `POST /i/api/graphql/:queryId/:operationName`
- `GET /1.1/*`
- `POST /1.1/*`
- `GET /2/*`
- `POST /2/*`

Profile selection is controlled by the `x-profile-name` header. If the header is
missing, the relay randomly selects a configured profile. For santasan, the
header should always be set to avoid cross-account actions.

The relay does not require santasan to generate cookies, CSRF tokens, or
`x-client-transaction-id`; those are handled by the browser-backed X Web App
client inside the relay.

## Required santasan actions

The current action surface is small:

- follow user
- repost
- like
- reply
- organic tweet

These can be represented with relay-compatible requests.

| santasan action | Relay request shape | Notes |
| --- | --- | --- |
| follow | `POST /1.1/friendships/create.json` | Body should contain `user_id` and the include flags twikit sends. Needs live verification because twikit used form-encoded data, while the relay route reads JSON. |
| repost | `POST /i/api/graphql/ojPdsZsimiJrUGLR1sjUtA/CreateRetweet` | Body: `{"variables":{"tweet_id": "...", "dark_request": false}, "queryId": "ojPdsZsimiJrUGLR1sjUtA"}`. |
| like | `POST /i/api/graphql/lI07N6Otwv1PhnEgXILM7A/FavoriteTweet` | Body: `{"variables":{"tweet_id": "..."}, "queryId": "lI07N6Otwv1PhnEgXILM7A"}`. |
| tweet | `POST /i/api/graphql/SiM_cAu83R0wnrpmKQQSEw/CreateTweet` | Body includes `tweet_text`, `media`, `semantic_annotation_ids`, `dark_request`, features, and `queryId`. |
| reply | Same as tweet | Add `variables.reply.in_reply_to_tweet_id`. |

The GraphQL query IDs above were verified from twikit 2.3.3 source. They are
private X Web App IDs and can change. A robust implementation should make them
configurable or easy to update.

## Headless Linux server feasibility

The relay supports Linux/headless deployment through Playwright.

Two practical modes:

1. `launch` mode
   - Relay launches a persistent Playwright browser context.
   - Configure `browser.type = "launch"`, `userDataDir`, and `headless = true`.
   - For initial login, temporarily run with `headless = false` or prepare the
     profile directory elsewhere, then reuse the same `userDataDir`.

2. `cdp` mode
   - Relay connects to an already-running Chromium instance over CDP.
   - The upstream Docker example uses `kasmweb/chrome` and a dashboard container.
   - This is the easiest server setup for first login because the browser UI is
     available over VNC/noVNC.

For production on a headless Linux host, CDP/Kasm is the safer operational
choice because login, challenge resolution, and session refresh are easier to
handle.

## Required changes in this repo

1. Replace `src/safe_relay.py` high-level fake routes with relay-native calls.
   - Add `_graphql_post(query_id, operation_name, variables, features=None)`.
   - Add `_v11_post(path, data)`.
   - Always send `x-profile-name`.

2. Fix account loading for safe-relay mode.
   - Do not instantiate twikit `Client` when `USE_SAFE_RELAY=true`.
   - Load account names from `accounts/account_configs.yaml` or a relay-specific
     profile list.
   - Ensure each santasan account name matches a relay `settings.json` profile.

3. Fix `actions.create_actions`.
   - The current SafeRelay branch returns an uninitialized object and has
     unreachable initialization code.

4. Update setup documentation.
   - Replace `/accounts` examples with `/profiles`.
   - Remove claims that relay exposes `/follow`, `/like`, etc.
   - Document `x-profile-name`.

5. Keep a live smoke test separate from unit tests.
   - `GET /health`
   - `GET /profiles`
   - `POST FavoriteTweet` against a controlled/private test tweet, or run only
     in dry-run/logging mode if real actions are not acceptable.

## Risks

- X Web App GraphQL query IDs can change.
- Follow through `/1.1/friendships/create.json` needs live validation with the
  relay because of JSON-vs-form body handling.
- The relay must maintain an active logged-in browser session. If X presents a
  challenge, santasan will not solve it by itself.
- Running fully headless from day one is awkward; prepare or refresh login state
  through a visible browser profile first.

## Recommendation

Proceed with the replacement, but treat it as an adapter rewrite rather than a
drop-in client swap. Implement the relay adapter first for tweet, reply, repost,
and like. Validate follow separately against a test account/profile. After that,
remove twikit from the runtime path used by `USE_SAFE_RELAY=true`.
