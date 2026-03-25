#!/usr/bin/env python3

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from icalendar import Calendar

def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        print(f"[ERROR] Invalid integer for {name}: {value}", file=sys.stderr)
        sys.exit(1)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    print(f"[ERROR] Invalid boolean for {name}: {value}", file=sys.stderr)
    sys.exit(1)


ICS_URL = os.getenv(
    "ICS_URL",
    "https://calendar.google.com/calendar/ical/nextspaceflight.com_l328q9n2alm03mdukb05504c44%40group.calendar.google.com/public/basic.ics",
)
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "",
)
CHECK_INTERVAL_SECONDS = env_int("CHECK_INTERVAL_SECONDS", 300)
TRIGGER_BEFORE_MINUTES = env_int("TRIGGER_BEFORE_MINUTES", 10)
STATE_FILE = os.getenv("STATE_FILE", "triggered_events.json")
USER_AGENT = os.getenv("USER_AGENT", "launch-discord-webhook/1.0")
DEBUG_MODE = env_bool("DEBUG_MODE", True)
PRELAUNCH_STATE_PREFIX = "prelaunch:"
T0_STATE_PREFIX = "t0:"
T0_TRIGGER_WINDOW_SECONDS = env_int(
    "T0_TRIGGER_WINDOW_SECONDS",
    CHECK_INTERVAL_SECONDS,
)


def load_state() -> set[str]:
    if not os.path.exists(STATE_FILE):
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            triggered: set[str] = set()
            for item in data:
                value = str(item)
                if value.startswith(PRELAUNCH_STATE_PREFIX) or value.startswith(
                    T0_STATE_PREFIX
                ):
                    triggered.add(value)
                else:
                    # Older state files stored only the prelaunch notification
                    # status by raw event ID.
                    triggered.add(f"{PRELAUNCH_STATE_PREFIX}{value}")
            return triggered
    except Exception as e:
        print(f"[WARN] Failed to load state file: {e}", file=sys.stderr)

    return set()


def save_state(triggered: set[str]) -> None:
    tmp_file = f"{STATE_FILE}.tmp"
    os.makedirs(os.path.dirname(os.path.abspath(tmp_file)), exist_ok=True)
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(sorted(triggered), f, indent=2)
    os.replace(tmp_file, STATE_FILE)


def fetch_calendar() -> Calendar:
    response = requests.get(
        ICS_URL,
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return Calendar.from_ical(response.content)


def normalize_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, datetime.min.time())

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def truncate(text: str | None, max_len: int) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_discord_timestamp(dt: datetime) -> str:
    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:F> (<t:{unix_ts}:R>)"


def notification_state_key(prefix: str, event_id: str) -> str:
    return f"{prefix}{event_id}"


def send_discord_webhook(
    title: str,
    event_id: str,
    summary: str,
    start_dt: datetime,
    location: str | None,
    description: str | None,
) -> None:
    embed = {
        "title": title,
        "description": truncate(summary, 4096) or "Untitled event",
        "fields": [
            {
                "name": "Launch Time",
                "value": format_discord_timestamp(start_dt),
                "inline": False,
            }
        ],
        "footer": {"text": "Source: Next Spaceflight calendar"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if location:
        embed["fields"].append(
            {
                "name": "Location",
                "value": truncate(location, 1024),
                "inline": False,
            }
        )

    if description:
        embed["fields"].append(
            {
                "name": "Details",
                "value": truncate(description, 1024),
                "inline": False,
            }
        )

    payload = {
        "username": "Launch Watcher",
        "embeds": [embed],
    }

    response = requests.post(
        DISCORD_WEBHOOK_URL,
        json=payload,
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    print(f"[OK] Sent Discord webhook for '{summary}' at {start_dt.isoformat()}")


def process_events(triggered: set[str]) -> set[str]:
    now = datetime.now(timezone.utc)
    trigger_deadline = now + timedelta(minutes=TRIGGER_BEFORE_MINUTES)

    cal = fetch_calendar()
    next_launch: tuple[str, str, datetime, str | None, str | None] | None = None
    sent_this_fetch: set[str] = set()

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        event_id = str(component.get("uid", "")).strip()
        summary = str(component.get("summary", "No title")).strip()

        dtstart_prop = component.get("dtstart")
        if not dtstart_prop:
            continue

        start_dt = normalize_dt(dtstart_prop.dt)
        location = str(component.get("location", "")).strip() or None
        description = str(component.get("description", "")).strip() or None

        if not event_id:
            event_id = f"{summary}-{start_dt.isoformat()}"

        if start_dt >= now and (
            next_launch is None or start_dt < next_launch[2]
        ):
            next_launch = (event_id, summary, start_dt, location, description)

        prelaunch_key = notification_state_key(PRELAUNCH_STATE_PREFIX, event_id)
        t0_key = notification_state_key(T0_STATE_PREFIX, event_id)
        t0_window_end = start_dt + timedelta(seconds=T0_TRIGGER_WINDOW_SECONDS)

        if now < start_dt <= trigger_deadline and prelaunch_key not in triggered:
            send_discord_webhook(
                title="🚀 Upcoming Launch",
                event_id=event_id,
                summary=summary,
                start_dt=start_dt,
                location=location,
                description=description,
            )
            sent_this_fetch.add(event_id)
            triggered.add(prelaunch_key)

        if start_dt <= now < t0_window_end and t0_key not in triggered:
            send_discord_webhook(
                title="🚀 T-0 Reached",
                event_id=event_id,
                summary=summary,
                start_dt=start_dt,
                location=location,
                description=description,
            )
            sent_this_fetch.add(event_id)
            triggered.add(t0_key)

    if next_launch is None:
        print("[DEBUG] No upcoming launches found on this fetch")
    else:
        next_event_id, next_summary, next_start_dt, next_location, next_description = (
            next_launch
        )
        print(
            f"[DEBUG] Next launch on this fetch: '{next_summary}' at {next_start_dt.isoformat()}"
        )
        if DEBUG_MODE and next_event_id not in sent_this_fetch:
            print(
                f"[DEBUG] Debug mode enabled, sending fetch webhook for '{next_summary}'"
            )
            send_discord_webhook(
                title="🚀 Upcoming Launch",
                event_id=next_event_id,
                summary=next_summary,
                start_dt=next_start_dt,
                location=next_location,
                description=next_description,
            )

    return triggered


def main() -> None:
    if not DISCORD_WEBHOOK_URL or "REPLACE_ME" in DISCORD_WEBHOOK_URL:
        print("[ERROR] Please set your Discord webhook URL first.", file=sys.stderr)
        sys.exit(1)

    triggered = load_state()
    print(f"[INFO] Launch watcher started (debug mode: {'on' if DEBUG_MODE else 'off'})")

    while True:
        try:
            triggered = process_events(triggered)
            save_state(triggered)
        except KeyboardInterrupt:
            print("\n[INFO] Stopped")
            break
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
