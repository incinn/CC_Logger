# CC Logger

Lightweight in-memory receiver for RuneLite's Chat Logger remote submission. It
deduplicates messages from multiple clients and forwards them to a Discord
webhook every X seconds.

## Run

Requires Python 3.14 and uv.

```bash
uv sync --extra dev
export INGEST_TOKEN="a-long-random-secret"
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
uv run cc-logger
```

The service listens on `0.0.0.0:8080` by default. Set `HOST` and `PORT` to
change the bind address. Configure the same `INGEST_TOKEN` in the plugin's
remote submission settings. The plugin sends it in the `Authorization` header.
Expose the endpoint over HTTPS or a trusted private network because this header
contains the shared secret.

## Ingest endpoint

`POST /messages` accepts the plugin's JSON array, containing up to 30 entries.
Each entry must include `id`, `timestamp`, `chatType`, `chatName`, `sender`,
and `message`. Only `chatType: "CLAN"` is accepted. Timestamps must
include a timezone. Batches containing any other chat type are rejected whole.

Successful requests return HTTP 202 with the count of newly buffered messages.
Repeated IDs are ignored. Invalid requests return HTTP 400, invalid tokens
return HTTP 401, and full in-memory buffers return HTTP 503.

## Discord delivery

Each message is formatted as:

```text
<t:UNIX:t> **sender** "message"
```

Discord renders `<t:UNIX:t>` as localized time in each viewer's timezone.
Messages whose sender matches `chatName` are detected as system messages
(collection log, rare drops etc) and are rendered slightly differently:

```text
-# <t:UNIX:t> *message*
```

Each webhook post starts with an invisible character and newline so the first
message appears on its own line. Messages are grouped into webhook posts under
Discord's 2,000-character limit. Mention parsing is disabled.

## Configuration

| Variable                 | Default   | Purpose                                       |
| ------------------------ | --------- | --------------------------------------------- |
| `HOST`                   | `0.0.0.0` | HTTP bind address                             |
| `PORT`                   | `8080`    | HTTP port                                     |
| `INGEST_TOKEN`           | Required  | Shared secret checked against `Authorization` |
| `DISCORD_WEBHOOK_URL`    | Required  | Discord incoming webhook URL                  |
| `FLUSH_INTERVAL_SECONDS` | `30`      | Webhook flush interval                        |
| `DEDUPE_TTL_SECONDS`     | `600`     | How long message IDs remain deduplicated      |
| `MAX_PENDING_MESSAGES`   | `20000`   | Maximum buffered chat lines                   |
| `MAX_DEDUPE_IDS`         | `100000`  | Maximum remembered message IDs                |

## Tests and formatting

```bash
uv run python -m unittest discover -s tests -v
uv run black . --check
uv lock --check
```
