"""Preview a daily automation; --apply creates it disabled for a first-run check."""

import argparse
import re
import shlex
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def command(chat_id, timezone="Europe/London", executable="openclaw", agent=None):
    if not re.fullmatch(r"[1-9][0-9]{3,19}", chat_id):
        raise ValueError("Use your numeric personal Telegram chat ID, not a username or group ID.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            "Timezone not found. On Windows, install it with: python -m pip install tzdata"
        ) from error
    args = [
        executable,
        "automations",
        "add",
        "--name",
        "Personal AI Briefing",
        "--cron",
        "0 8 * * *",
        "--tz",
        timezone,
        "--session",
        "isolated",
        "--disabled",
        "--announce",
        "--channel",
        "telegram",
        "--to",
        chat_id,
        "--message",
        "Use the ai-briefing skill to prepare my current personal AI briefing. "
        "Use live feeds, focus on AI agents, retrieval, evaluation and practical engineering. "
        "Keep it under 3500 characters, cite source URLs, mention failed sources and include a 30-minute learning sprint. "
        "Return the final text; this automation handles delivery. Do not acknowledge delivery before it succeeds.",
    ]
    if agent:
        args += ["--agent", agent]
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--timezone", default="Europe/London")
    parser.add_argument("--agent", help="Agent whose workspace contains the skill.")
    parser.add_argument("--openclaw", default="openclaw", help="OpenClaw executable path, if not on PATH.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        argv = command(args.chat_id, args.timezone, args.openclaw, args.agent)
        if args.apply:
            return subprocess.run(argv, check=False).returncode
        print("Preview only. No automation was created.\n" + shlex.join(argv))
        print("\nUse --apply to create it disabled. Test and enable it with the returned job ID.")
        return 0
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
