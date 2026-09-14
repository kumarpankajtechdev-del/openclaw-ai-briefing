# Personal AI Briefing · OpenClaw

An independent learning assistant by **Pankaj Kumar**. Curate AI engineering reading from primary-source feeds, keep source links, and turn a useful topic into a 30-minute learning sprint.

The project has two clear layers:

1. A **working Python curation engine**: feed ingestion, URL/title deduplication, freshness filtering, relevance ranking, source diversity and HTML/Markdown/JSON output.
2. A **native OpenClaw skill**: your configured OpenAI or Anthropic model explains the selected items; OpenClaw handles Telegram conversations and scheduled delivery.

No employer data, private code or company performance claims are included.

## Run the offline demo first

Use Python 3.11 or newer; Python 3.12 was tested. No Python packages, OpenClaw installation or API key are needed for this preview.

~~~bash
python run.py --demo
~~~

Open **reports/briefing-demo.html**. It contains four clearly labelled fictional learning cards with primary documentation links. Dates are relative to the run, so the demo does not expire. The preview uses deterministic curation and a template learning plan; it does not simulate a model call.

You can run the script from another directory using its absolute path. Output goes to the current directory unless you set --out.

## Fetch current reading

~~~bash
python run.py --live
~~~

Open reports/briefing.html. The machine-readable packet is reports/briefing.json.

Configured primary-source feeds:

- [OpenAI News](https://openai.com/news/rss.xml)
- [Hugging Face Blog](https://huggingface.co/blog/feed.xml)
- [LangChain Blog](https://www.langchain.com/blog/rss.xml)

The engine reads feed excerpts, not full articles. It filters to the last seven days by default, excludes missing/future dates, matches configured engineering topics, and keeps at most two items per source. It does not pad an empty briefing with older material.

~~~bash
python run.py --live --days 3 --limit 4 --topics agents retrieval evaluation
~~~

A source can be unavailable or rate-limited. Partial failures appear in the report; all-source failure exits nonzero and does not mark any item delivered.

## Add it to OpenClaw

The local skill installation and CLI syntax were checked against **OpenClaw 2026.9.4**. That release requires Node 24.16+ in the 24 series or Node 26.1+; use a supported release. Linux with Node 24.19.0 was used for the checks.

If OpenClaw is already configured, skip onboarding. For a new installation:

~~~bash
npm install -g openclaw@2026.9.4
openclaw onboard
~~~

Choose your own OpenAI or Anthropic authentication and a model your account supports. Model usage can incur charges. Do not put credentials in this repository.

From the project root:

~~~bash
openclaw skills install ./openclaw/skills/ai-briefing --as ai-briefing
openclaw skills info ai-briefing --json
~~~

The result should report eligible and modelVisible as true. The skill requires **python3** on the OpenClaw host. On Windows, make sure that exact command works or run the gateway in WSL with Python installed. The report-only demo can use the ordinary python command.

If you use several agents, install into the intended agent's workspace with --agent YOUR_AGENT_ID and use the same agent for scheduling. Start a fresh chat after installation.

Ask the agent:

> Use the ai-briefing skill in demo mode. Explain the selected learning cards with source links.

Then:

> Use the ai-briefing skill to create my current briefing from live feeds.

OpenClaw must be able to run the bundled Python helper. If your tool policy or sandbox restricts execution/network access, keep that policy and use the report-only mode or explicitly configure the required access yourself. The skill does not disable protections.

## Connect your personal Telegram bot

1. Create your bot through Telegram's official BotFather. Keep the token private.
2. Run **openclaw channels add** and choose Telegram, or use the official setup guide's token configuration.
3. Keep DM pairing enabled. Start your bot in Telegram and send it a message.
4. On your gateway host, run:

~~~bash
openclaw pairing list telegram
openclaw pairing approve telegram PAIRING_CODE
openclaw channels status --probe
~~~

Replace PAIRING_CODE with the code from your own pairing request. Confirm that the intended account is paired before sending private content.

Use the numeric sender/chat ID shown in your own incoming Telegram message or pairing details in OpenClaw. Do not use the bot's numeric ID as your personal chat ID.

Ask the bot to run a demo briefing before scheduling it. This is where you verify the complete model → skill → Telegram flow with your credentials.

## Schedule a morning briefing

The helper defaults to **08:00 Europe/London**, including daylight-saving changes.

Preview the exact command without changing anything:

~~~bash
python scripts/schedule.py --chat-id YOUR_NUMERIC_CHAT_ID
~~~

Create it disabled, so you can inspect and test your own destination:

~~~bash
python scripts/schedule.py --chat-id YOUR_NUMERIC_CHAT_ID --apply
~~~

Use the job ID returned by OpenClaw:

~~~bash
openclaw automations get JOB_ID
openclaw automations run JOB_ID
openclaw automations runs JOB_ID --limit 5
openclaw automations enable JOB_ID
~~~

A manual run can send a real Telegram message and call your model. Check the first message before enabling the schedule. The gateway must stay running for scheduled work. For an always-on host, use OpenClaw's documented gateway service installation and check **openclaw gateway status**.

To stop the schedule:

~~~bash
openclaw automations disable JOB_ID
~~~

On Windows, if timezone data is missing, install it with **python -m pip install tzdata**. If the OpenClaw executable is not on PATH, supply --openclaw with its full path.

## Delivery history: an honest boundary

Within each run, duplicate URLs/titles are removed automatically. Across runs, stories are suppressed **after a delivery acknowledgement**.

Generation does not prove delivery. To avoid losing stories when Telegram fails, the skill does not mark them delivered during generation. After checking a successful message, ask the agent to acknowledge that exact run ID, or run the bundled helper with --ack RUN_ID and the same state folder.

For standalone runs:

~~~bash
python run.py --ack YOUR_RUN_ID
~~~

The installed skill uses its own state directory, separate from standalone runs. Only locally generated live run IDs are accepted; acknowledgement is idempotent. Without acknowledgement, stories may repeat within the lookback window. This project does not claim automatic exactly-once delivery.

## Tests

~~~bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
~~~

Coverage includes RSS/Atom parsing, tracking-link removal, duplicate detection, freshness, source limits, XML/URL validation, partial outages, all-source failure, delivery acknowledgement, HTML escaping and execution from a different directory.

The GitHub Actions workflow uses offline fixtures and makes no paid model calls.

See docs/VERIFICATION.md for the handover checks. Live OpenAI/Anthropic completions and Telegram delivery require your own credentials and were not verified in this environment.

## Why this is useful to show

The strongest part of this project is its separation of responsibilities: deterministic curation and durable history, model-written explanations with source IDs, and native OpenClaw scheduling/delivery. Show the offline preview first, then demonstrate a live Telegram message only after you have configured and tested it.

Suggested portfolio wording:

**Personal AI Briefing Assistant — OpenClaw**  
Built a personal learning assistant with primary-source feed ingestion, deduplication, relevance ranking and cited briefings, with a native OpenClaw skill for model-assisted explanations and configurable Telegram scheduling.

Say "deployed" or "always-on" only once you have actually run the gateway and confirmed scheduled messages.

## Official integration references

- [OpenClaw getting started](https://docs.openclaw.ai/start/getting-started)
- [Skills and workspace installation](https://docs.openclaw.ai/tools/skills)
- [Telegram setup](https://docs.openclaw.ai/channels/telegram/setup)
- [Managing scheduled jobs](https://docs.openclaw.ai/automation/cron-jobs/managing-jobs)

MIT licensed. See LICENSE.
