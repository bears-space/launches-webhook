# Launches Webhook

Small Python service that watches the public Next Spaceflight iCal feed and sends Discord webhook notifications for launches.

## Features

- Polls the launch calendar on a configurable interval
- Sends one `🚀 Upcoming Launch` notification shortly before launch
- Sends one `🚀 T-0 Reached` notification when the scheduled launch time is reached
- Logs the next upcoming launch on every fetch for debugging
- Can optionally send a debug webhook on every fetch for the next launch
- Persists notification state to disk so restarts do not resend the same alerts

## How It Works

On each fetch, the watcher downloads the public calendar feed from Next Spaceflight, parses all `VEVENT` entries, finds the next upcoming launch, and decides whether to send notifications.

The normal notification flow is:

- `🚀 Upcoming Launch` once when an event enters the pre-launch window
- `🚀 T-0 Reached` once when the scheduled launch time is reached

When debug mode is enabled, the service also sends an extra `🚀 Upcoming Launch` webhook on every fetch for the next upcoming launch.

## Configuration

The Discord webhook URL is not stored in this repository. You must provide it through environment variables.

| Variable | Default | Description |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | none | Required. Discord webhook URL used for notifications. |
| `ICS_URL` | Next Spaceflight public iCal feed | Calendar source to poll. |
| `CHECK_INTERVAL_SECONDS` | `300` | How often the calendar is fetched. |
| `TRIGGER_BEFORE_MINUTES` | `10` | Minutes before launch to send the pre-launch alert. |
| `T0_TRIGGER_WINDOW_SECONDS` | `CHECK_INTERVAL_SECONDS` | Grace window used to catch the T-0 notification on the next poll. |
| `STATE_FILE` | `triggered_events.json` | Path to the JSON state file. |
| `USER_AGENT` | `launch-discord-webhook/1.0` | HTTP user agent used for requests. |
| `DEBUG_MODE` | `true` in `main.py`, `false` in Docker | Enables extra fetch-time webhook sends. |

## Docker

Build the image:

```bash
docker build -t launcheswebhook .
```

Run it:

```bash
docker run -d \
  --name launcheswebhook \
  -e DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...' \
  -e DEBUG_MODE=false \
  -v launcheswebhook-data:/data \
  launcheswebhook
```

Watch logs:

```bash
docker logs -f launcheswebhook
```

The Docker image stores state in `/data/triggered_events.json`, so mounting `/data` keeps notification state across container restarts.

## Local Development

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the watcher:

```bash
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
export DEBUG_MODE=false
python main.py
```

## Example Debug Run

If you want the watcher to send a webhook on every fetch for the next launch, enable debug mode:

```bash
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
export DEBUG_MODE=true
python main.py
```

## Files

- `main.py`: main watcher process
- `Dockerfile`: container image definition
- `requirements.txt`: Python dependencies
- `triggered_events.json`: persisted notification state at runtime

## Security

- Do not commit real Discord webhook URLs
- Pass secrets through environment variables or your deployment platform
- If a webhook was ever committed or shared, rotate it in Discord before using this project publicly
