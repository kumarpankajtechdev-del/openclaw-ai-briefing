import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = load("briefing", ROOT / "openclaw/skills/ai-briefing/scripts/briefing.py")
s = load("schedule", ROOT / "scripts/schedule.py")
NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


def article(title="Agent evaluation", url="https://openai.com/news/example", source="OpenAI", hours=2):
    return {
        "title": title,
        "url": url,
        "source": source,
        "published": (NOW - timedelta(hours=hours)).isoformat(),
        "excerpt": "An original test fixture about agents, evaluation and retrieval.",
    }


def test_demo_without_network_or_delivery_history(tmp_path):
    def forbidden(*args):
        raise AssertionError("Offline demo used the network")

    result = b.collect(demo=True, now=NOW, state=tmp_path, fetcher=forbidden)
    assert result["mode"] == "demo" and len(result["articles"]) == 4
    assert not (tmp_path / "history.sqlite3").exists()
    assert all("Demo learning card:" in item["title"] for item in result["articles"])


def test_rss_atom_dates_and_tracking():
    rss = b"""<rss><channel><item><title>Agent eval</title><link>https://openai.com/news/a/?utm_source=x</link>
    <pubDate>Mon, 14 Sep 2026 07:00:00 GMT</pubDate><description>&lt;b&gt;Models&lt;/b&gt; and evaluation</description>
    </item></channel></rss>"""
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Retrieval</title>
    <link href="https://huggingface.co/blog/example" rel="alternate"/>
    <updated>2026-09-14T07:00:00Z</updated><summary>Model agents</summary></entry></feed>"""
    assert b.parse_feed(rss, "OpenAI")[0]["url"] == "https://openai.com/news/a"
    assert b.parse_feed(rss, "OpenAI")[0]["excerpt"] == "Models and evaluation"
    assert b.parse_feed(atom, "Hugging Face")[0]["published"].endswith("+00:00")


@pytest.mark.parametrize(
    "url",
    [
        "http://openai.com/news/a",
        "https://127.0.0.1/a",
        "https://openai.com.attacker.test/a",
        "https://x:secret@openai.com/a",
        "https://openai.com:9999/a",
        "javascript:alert(1)",
    ],
)
def test_unsafe_links(url):
    with pytest.raises(ValueError):
        b.canonical_url(url)


def test_dtd_and_size():
    with pytest.raises(ValueError):
        b.parse_feed(b'<!DOCTYPE foo [<!ENTITY x "boom">]><rss/>', "x")
    with pytest.raises(ValueError):
        b.parse_feed(b"x" * (b.MAX_BYTES + 1), "x")


def test_freshness_duplicates_and_source_cap():
    items = [
        article(),
        article(url="https://openai.com/news/example?utm_source=x"),
        article("Different title", "https://openai.com/news/example"),
        article("Old agent", "https://openai.com/news/old", hours=999),
        article("Future agent", "https://openai.com/news/future", hours=-99),
        article("Missing date", "https://openai.com/news/missing"),
    ]
    items[-1]["published"] = None
    assert len(b.select_articles(items, NOW)) == 1
    more = [article("Agent " + str(i), "https://openai.com/news/" + str(i)) for i in range(6)]
    assert len(b.select_articles(more, NOW, limit=6)) == 2


def test_partial_failure_and_delivery_ack(tmp_path):
    def fetch(source, url):
        if source == "OpenAI":
            raise URLError("source unavailable")
        return [article(source + " agent", url, source)]

    packet = b.collect(now=NOW, state=tmp_path, fetcher=fetch)
    assert packet["sources_succeeded"] == 2 and len(packet["source_errors"]) == 1
    assert b.read_seen(tmp_path) == set()
    assert b.acknowledge(packet["run_id"], tmp_path)["articles"] == 2
    assert b.acknowledge(packet["run_id"], tmp_path)["articles"] == 2
    assert b.collect(now=NOW, state=tmp_path, fetcher=fetch)["status"] == "no_new_matches"


def test_all_feeds_fail(tmp_path):
    def fail(*args):
        raise URLError("failed")

    with pytest.raises(ValueError, match="All sources failed"):
        b.collect(now=NOW, state=tmp_path, fetcher=fail)
    assert not (tmp_path / "history.sqlite3").exists()
    with pytest.raises(ValueError, match="Unknown run"):
        b.acknowledge("invented", tmp_path)


def test_html_escaping():
    packet = b.collect(demo=True, now=NOW)
    packet["articles"][0]["title"] = '<script>alert("x")</script>'
    rendered = b.render_html(packet)
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered


def test_cli_from_other_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--demo", "--json"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "demo"
    assert (tmp_path / "reports/briefing-demo.html").exists()


def test_schedule_arguments():
    args = s.command("123456789")
    assert "--disabled" in args and "--announce" in args
    assert args[args.index("--tz") + 1] == "Europe/London"
    with pytest.raises(ValueError):
        s.command("1234; echo injected")
