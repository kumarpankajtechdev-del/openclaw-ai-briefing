#!/usr/bin/env python3
"""Standard-library curation engine. OpenClaw supplies the model and Telegram delivery."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = Path(__file__).resolve().parents[1]
FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("LangChain", "https://www.langchain.com/blog/rss.xml"),
]
HOSTS = {
    "openai.com",
    "www.openai.com",
    "huggingface.co",
    "www.langchain.com",
    "blog.langchain.com",
    "langchain-blog.ghost.io",
}
LINK_HOSTS = HOSTS | {"developers.openai.com", "docs.langchain.com", "python.langchain.com"}
TOPICS = {
    "agents": ("agent", "agents", "agentic", "tool use", "tool calling"),
    "retrieval": ("rag", "retrieval", "embedding", "embeddings"),
    "evaluation": ("evaluation", "evaluations", "eval", "evals", "benchmark"),
    "models": ("model", "models", "inference", "reasoning"),
    "engineering": ("deployment", "production", "latency", "observability", "python"),
}
MAX_BYTES = 2_000_000


def canonical_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in LINK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only HTTPS links from configured primary sources are accepted.")
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query)
        if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source", "trk"}
    ]
    return urlunsplit(
        ("https", parsed.hostname, parsed.path.rstrip("/") or "/", urlencode(sorted(query)), "")
    )


def clean_text(value, limit=1200):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())[:limit]


def parse_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def parse_feed(data, source):
    if len(data) > MAX_BYTES or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Feed exceeds the size limit or contains unsupported XML declarations.")
    root = ET.fromstring(data)
    rows = root.findall("./channel/item")
    atom = "{http://www.w3.org/2005/Atom}"
    if not rows:
        rows = root.findall(atom + "entry")
    result = []
    for row in rows[:500]:

        def value(*names):
            for name in names:
                node = row.find(name)
                if node is not None:
                    return "".join(node.itertext()).strip()
            return ""

        link = value("link")
        if not link:
            links = [
                node.get("href", "")
                for node in row.findall(atom + "link")
                if node.get("rel", "alternate") == "alternate"
            ]
            link = links[0] if links else ""
        try:
            link = canonical_url(link)
        except ValueError:
            continue
        title = clean_text(value("title", atom + "title"), 220)
        if not title:
            continue
        published = parse_date(
            value("pubDate", atom + "published", atom + "updated", "{http://purl.org/dc/elements/1.1/}date")
        )
        result.append(
            {
                "title": title,
                "url": link,
                "source": source,
                "published": published.isoformat() if published else None,
                "excerpt": clean_text(value("description", atom + "summary", atom + "content")),
            }
        )
    return result


class AllowedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (
            target.scheme != "https"
            or target.hostname not in HOSTS
            or target.port not in (None, 443)
            or target.username
        ):
            raise ValueError("Feed redirected outside configured source hosts.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_feed(source, url):
    opener = build_opener(AllowedRedirect())
    request = Request(
        url,
        headers={
            "User-Agent": "PersonalAIBriefing/1.0 (RSS reader)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    )
    with opener.open(request, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
    return parse_feed(data, source)


def fingerprint(title):
    return hashlib.sha256(re.sub(r"\W+", "", title.casefold()).encode()).hexdigest()


def select_articles(articles, now, limit=5, days=7, seen=None, topics=None):
    seen = seen or set()
    topics = topics or list(TOPICS)
    candidates, urls, titles = [], set(), set()
    for original in articles:
        article = dict(original)
        published = parse_date(article.get("published"))
        if not published or not now - timedelta(days=days) <= published <= now + timedelta(hours=1):
            continue
        try:
            url = canonical_url(article["url"])
        except ValueError:
            continue
        article["url"] = url
        title_id = fingerprint(article["title"])
        if url in urls or title_id in titles or url in seen or title_id in seen:
            continue
        text = (article["title"] + " " + article["excerpt"]).casefold()
        matches = [
            topic
            for topic in topics
            if any(re.search(r"\b" + re.escape(term) + r"\b", text) for term in TOPICS[topic])
        ]
        if not matches:
            continue
        age = max(0, (now - published).total_seconds() / 86400)
        article.update(
            topics=matches,
            score=round(3 * len(matches) + max(0, 2 - age / max(days, 1) * 2), 3),
            title_id=title_id,
        )
        candidates.append(article)
        urls.add(url)
        titles.add(title_id)
    candidates.sort(key=lambda a: (-a["score"], a["url"]))
    selected, counts = [], Counter()
    for article in candidates:
        if counts[article["source"]] >= 2:
            continue
        selected.append({**article, "id": f"S{len(selected) + 1}"})
        counts[article["source"]] += 1
        if len(selected) == limit:
            break
    return selected


@contextmanager
def state_db(directory):
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "history.sqlite3", timeout=15)
    db.execute("CREATE TABLE IF NOT EXISTS seen(key TEXT PRIMARY KEY, acknowledged_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS packets(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    try:
        with db:
            yield db
    finally:
        db.close()


def read_seen(directory):
    with state_db(directory) as db:
        return {row[0] for row in db.execute("SELECT key FROM seen")}


def acknowledge(run_id, directory):
    with state_db(directory) as db:
        row = db.execute("SELECT payload FROM packets WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(
                "Unknown run ID; only a packet generated in this state directory can be acknowledged."
            )
        packet = json.loads(row[0])
        if packet["mode"] != "live":
            raise ValueError("Demo packets do not change delivery history.")
        timestamp = datetime.now(timezone.utc).isoformat()
        for item in packet["articles"]:
            for key in (item["url"], item["title_id"]):
                db.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (key, timestamp))
    return {"acknowledged": run_id, "articles": len(packet["articles"])}


def collect(demo=False, now=None, limit=5, days=7, state=None, topics=None, fetcher=fetch_feed):
    now = now or datetime.now(timezone.utc)
    errors, articles = [], []
    if demo:
        fixture = json.loads((BASE / "fixtures/demo.json").read_text(encoding="utf-8"))
        # Demo dates are relative to the requested run date so the preview never expires.
        for item in fixture:
            item = dict(item)
            item["published"] = (now - timedelta(hours=item.pop("age_hours"))).isoformat()
            articles.append(item)
        successful = len({a["source"] for a in articles})
    else:

        def fetch(pair):
            source, url = pair
            try:
                return fetcher(source, url), None
            except (URLError, OSError, ValueError, ET.ParseError) as error:
                return [], {"source": source, "error": type(error).__name__}

        with ThreadPoolExecutor(max_workers=3) as pool:
            for rows, error in pool.map(fetch, FEEDS):
                articles.extend(rows)
                if error:
                    errors.append(error)
        successful = len(FEEDS) - len(errors)
        if successful == 0:
            raise ValueError(
                "All sources failed. No briefing was generated; delivery history was not changed."
            )
    selected = select_articles(
        articles, now, limit, days, read_seen(state) if state and not demo else set(), topics
    )
    packet = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "mode": "demo" if demo else "live",
        "generated_at": now.isoformat(),
        "lookback_days": days,
        "sources_succeeded": successful,
        "source_errors": errors,
        "candidate_count": len(articles),
        "articles": selected,
        "status": "ready" if selected else "no_new_matches",
        "note": "Fictional learning examples, not current news."
        if demo
        else "Feed excerpts only; full articles are not fetched. Ranking scores are heuristics, not confidence scores.",
    }
    if state and not demo:
        with state_db(state) as db:
            db.execute("INSERT INTO packets VALUES(?,?)", (packet["run_id"], json.dumps(packet)))
    return packet


def learning_plan(article):
    return [
        "10 min · Read the linked primary source and note its main claim and limitations.",
        "15 min · Build one small example related to " + article["topics"][0] + ".",
        "5 min · Write down one failure case and one check you would add before using it.",
    ]


def markdown(packet):
    lines = [
        "# Personal AI Briefing",
        "",
        "**" + packet["mode"].upper() + "** · " + packet["generated_at"][:10],
        "",
        packet["note"],
        "",
    ]
    if packet["source_errors"]:
        lines += ["Source failures: " + ", ".join(e["source"] for e in packet["source_errors"]) + ".", ""]
    for item in packet["articles"]:
        # Excerpts remain in the machine packet for grounding; public previews link and identify topics.
        title = item["title"].replace("[", "(").replace("]", ")").replace("\n", " ")
        lines += [
            f"## [{item['id']}] {title}",
            f"Source: [{item['source']}]({item['url']})",
            "Matched interests: " + ", ".join(item["topics"]) + ".",
            "",
        ]
    if packet["articles"]:
        lines += ["## Today's learning sprint", ""] + [
            "- " + step for step in learning_plan(packet["articles"][0])
        ]
    else:
        lines += ["No new matching articles in this time window. No older story was substituted."]
    return "\n".join(lines) + "\n"


def render_html(packet):
    cards = []
    for item in packet["articles"]:
        tags = " · ".join(item["topics"])
        cards.append(
            '<article><p class="source">'
            + html.escape(item["source"])
            + " / "
            + html.escape(item["id"])
            + "</p><h2>"
            + html.escape(item["title"])
            + "</h2><p>"
            + html.escape(tags)
            + '</p><a rel="noreferrer" href="'
            + html.escape(item["url"], quote=True)
            + '">Read the primary source ↗</a></article>'
        )
    plan = (
        "".join("<li>" + html.escape(step) + "</li>" for step in learning_plan(packet["articles"][0]))
        if packet["articles"]
        else ""
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Personal AI Briefing</title><style>body{margin:0;background:#f6f5f0;color:#182f3b;font:16px/1.6 system-ui}"
        "main{max-width:900px;margin:auto;padding:48px 24px}header{border-bottom:2px solid #182f3b;padding-bottom:24px}"
        "h1{font-size:48px;line-height:1.1;letter-spacing:-2px;margin:15px 0}h2{font-size:22px;line-height:1.3}"
        ".tag,.source{font-size:11px;letter-spacing:1.8px;text-transform:uppercase}.tag{background:#dceca2;padding:6px 10px}"
        "p{color:#536977}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:28px 0}article{padding:24px;"
        "background:white;border:1px solid #dbe1df;border-radius:14px}a{color:#176457;font-size:13px}section{padding:25px;"
        "background:#e8eee2;border-radius:14px}footer{font-size:12px;margin-top:25px}@media(max-width:600px){.grid{grid-template-columns:1fr}h1{font-size:38px}}</style>"
        '<main><header><span class="tag">'
        + packet["mode"].upper()
        + " · "
        + packet["generated_at"][:10]
        + "</span>"
        "<h1>Your AI learning, curated.</h1><p>A focused reading list and one practical learning sprint.</p><p>"
        + html.escape(packet["note"])
        + "</p></header><p>"
        + str(packet["sources_succeeded"])
        + " sources available · "
        + str(len(packet["articles"]))
        + " selected items</p><p>"
        + html.escape(
            "Unavailable sources: " + ", ".join(e["source"] for e in packet["source_errors"])
            if packet["source_errors"]
            else ""
        )
        + '</p><div class="grid">'
        + ("".join(cards) or "<p>No new matching articles in this time window.</p>")
        + "</div><section><h2>A 30-minute learning sprint</h2><ol>"
        + plan
        + "</ol></section>"
        "<footer>Independent personal project by Pankaj Kumar. OpenClaw adds model-written summaries, Telegram and scheduling.</footer></main></html>"
    )


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Offline fictional examples; no API key needed.")
    parser.add_argument("--live", action="store_true", help="Fetch current primary-source RSS feeds.")
    parser.add_argument("--out", type=Path, default=Path("reports"))
    parser.add_argument("--state", type=Path, default=Path(".briefing-state"))
    parser.add_argument("--limit", type=int, choices=range(1, 7), default=5)
    parser.add_argument("--days", type=int, choices=range(1, 31), default=7)
    parser.add_argument("--topics", nargs="+", choices=list(TOPICS), default=list(TOPICS))
    parser.add_argument(
        "--ack", metavar="RUN_ID", help="Mark a live packet delivered after checking delivery."
    )
    parser.add_argument("--json", action="store_true", help="Print only the machine-readable packet.")
    args = parser.parse_args(argv)
    try:
        if args.ack:
            if args.demo or args.live:
                parser.error("--ack cannot be combined with --demo or --live")
            print(json.dumps(acknowledge(args.ack, args.state)))
            return 0
        if args.demo == args.live:
            parser.error("Choose exactly one of --demo or --live.")
        packet = collect(args.demo, limit=args.limit, days=args.days, state=args.state, topics=args.topics)
        name = "briefing-demo" if args.demo else "briefing"
        atomic_write(args.out / (name + ".json"), json.dumps(packet, indent=2, ensure_ascii=False))
        atomic_write(args.out / (name + ".md"), markdown(packet))
        atomic_write(args.out / (name + ".html"), render_html(packet))
        print(
            json.dumps(packet, ensure_ascii=False)
            if args.json
            else f"{packet['mode'].upper()}: {len(packet['articles'])} items. Open {args.out / (name + '.html')}\nRun ID: {packet['run_id']}"
        )
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print("Briefing failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
