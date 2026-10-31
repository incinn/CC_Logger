# CC Logger

Lightweight in-memory server for the RuneLite
[Chat Logger plugin](https://runelite.net/plugin-hub/show/chat-logger) remote
submission. It deduplicates messages from multiple clients and forwards them to
a Discord webhook every X seconds.

## Docker

Copy `.env.example` to `.env` and set real values for `INGEST_TOKEN` and
`DISCORD_WEBHOOK_URL`. Start development or production container with:

```bash
make up       # development image (source and tests mounted)
make up-prod  # production image
make down     # stop server
```

Both modes use port `8080` by default. Run only one mode at a time. Set `PORT`
to change the app and exposed port. The service keeps its buffer in memory, so
restarting the container clears pending messages and dedupe history.

## Ingest endpoint

`POST /messages` accepts the plugin's JSON array, containing up to 30 entries.
Each entry must include `id`, `timestamp`, `chatType`, `chatName`, `sender`, and
`message`. Only `chatType: "CLAN"` is accepted. Timestamps must include a
timezone. Batches containing any other chat type are rejected whole.

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

## Makefile

| Target                               | Purpose                                                    |
| ------------------------------------ | ---------------------------------------------------------- |
| `make test` / `make test-prod`       | Run unit tests in development or production container      |
| `make format`                        | Format Python code with Black in the development container |
| `make shell`                         | Open shell in the development container                    |
| `make build-dev` / `make build-prod` | Build development or production image                      |
| `make rmi-dev` / `make rmi-prod`     | Remove local development or production image               |
| `make update-deps`                   | Upgrade lockfile and rebuild development image             |
| `make clean`                         | Stop project containers and remove project images          |

## CI and image publishing

Pull requests run unit tests, lockfile validation, and formatting checks. Pushes
to `main` run the same checks, then publish the production image to GitHub
Container Registry as `latest` and `sha-<commit>` tags.

## Tests and formatting

```bash
uv run python -m unittest discover -s tests -v
uv run black . --check
uv lock --check
```
