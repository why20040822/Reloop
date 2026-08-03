#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""Polite public/authorized resume crawler based on httpx + BeautifulSoup.

This crawler is intentionally conservative:
- static HTML only;
- no login, cookie replay, captcha bypass, proxy rotation, or anti-bot evasion;
- respects robots.txt by default;
- stores source URL, raw visible text, and collection metadata for downstream
  evidence-based parsing in reloop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
from bs4 import BeautifulSoup


DEFAULT_USER_AGENT = "TTCResumeCrawler/0.1 (+authorized recruiting research)"
RESUME_HINTS = (
    "简历", "履历", "个人简介", "工作经历", "项目经历", "教育经历", "教育背景",
    "求职意向", "候选人", "resume", "cv", "curriculum vitae", "work experience",
    "education", "projects", "skills", "experience",
)
NEGATIVE_LINK_HINTS = (
    "login", "signin", "register", "privacy", "terms", "help", "about", "contact",
    "logout", "javascript:", "mailto:", "tel:",
)
BLOCKED_HINTS = (
    "请输入验证码", "安全验证", "访问过于频繁", "异常访问", "请完成验证",
    "登录后查看", "captcha", "verify you are human",
)


@dataclass
class CrawlItem:
    url: str
    title: str
    text: str
    text_hash: str
    matched_keywords: list[str]
    collected_at: str
    access_basis: str
    source_type: str = "public_web_resume"


def normalize_url(url: str, base: str | None = None) -> str:
    if base:
        url = urllib.parse.urljoin(base, url)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    cleaned = parsed._replace(fragment="")
    return urllib.parse.urlunparse(cleaned)


def host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def robots_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


class RobotsCache:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self.cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        key = robots_url(url)
        parser = self.cache.get(key)
        if not parser:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(key)
            try:
                parser.read()
            except Exception:
                return True
            self.cache[key] = parser
        return parser.can_fetch(self.user_agent, url)


def visible_text_and_links(html: str, url: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""

    parts: list[str] = []
    for node in soup.find_all(["h1", "h2", "h3", "p", "li", "td", "th", "section", "article", "div"]):
        text = node.get_text(" ", strip=True)
        if not text or len(text) < 2:
            continue
        if len(text) > 5000:
            continue
        parts.append(text)

    seen_lines: set[str] = set()
    lines: list[str] = []
    for raw in "\n".join(parts).splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in seen_lines:
            continue
        seen_lines.add(line)
        lines.append(line)

    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"], url)
        if href:
            links.append(href)
    return title, "\n".join(lines), links


def matched_resume_keywords(title: str, text: str, url: str) -> list[str]:
    haystack = f"{title}\n{url}\n{text[:12000]}".lower()
    return [word for word in RESUME_HINTS if word.lower() in haystack]


def link_priority(url: str, label: str = "") -> int:
    value = f"{url} {label}".lower()
    if any(hint in value for hint in NEGATIVE_LINK_HINTS):
        return -10
    score = 0
    for hint in RESUME_HINTS:
        if hint.lower() in value:
            score += 5
    if re.search(r"(resume|cv|profile|candidate|talent|person|people|team)", value, re.I):
        score += 2
    return score


def should_keep_page(title: str, text: str, url: str, min_chars: int, min_keywords: int) -> tuple[bool, list[str]]:
    if len(text.strip()) < min_chars:
        return False, []
    if any(hint.lower() in text.lower() for hint in BLOCKED_HINTS):
        return False, []
    matches = matched_resume_keywords(title, text, url)
    return len(matches) >= min_keywords, matches


def iter_seeds(args: argparse.Namespace) -> Iterable[str]:
    for seed in args.seed:
        normalized = normalize_url(seed)
        if normalized:
            yield normalized
    if args.seed_file:
        for raw in Path(args.seed_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            normalized = normalize_url(line)
            if normalized:
                yield normalized


def post_to_collector(item: CrawlItem, collector_url: str) -> dict:
    payload = {
        "url": item.url,
        "title": item.title,
        "heading": item.title,
        "text": item.text,
        "platform": host(item.url),
        "source_type": item.source_type,
        "captured_at": item.collected_at,
        "structured_data": {
            "access_basis": item.access_basis,
            "matched_keywords": item.matched_keywords,
            "text_hash": item.text_hash,
        },
    }
    with httpx.Client(timeout=30.0, trust_env=False) as client:
        response = client.post(collector_url.rstrip("/") + "/api/capture", json=payload)
        response.raise_for_status()
        return response.json()


def crawl(args: argparse.Namespace) -> int:
    seeds = list(dict.fromkeys(iter_seeds(args)))
    if not seeds:
        print("No valid seed URL provided", file=sys.stderr)
        return 2

    queue: deque[tuple[str, int]] = deque((seed, 0) for seed in seeds)
    seed_hosts = {host(seed) for seed in seeds}
    seen: set[str] = set()
    emitted_hashes: set[str] = set()
    robots = RobotsCache(args.user_agent)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": args.user_agent, "Accept": "text/html,application/xhtml+xml"}
    saved = 0
    fetched = 0

    with httpx.Client(headers=headers, follow_redirects=True, timeout=args.timeout, trust_env=False) as client:
        with output_path.open("w", encoding="utf-8") as out:
            while queue and fetched < args.max_pages:
                url, depth = queue.popleft()
                if url in seen:
                    continue
                seen.add(url)
                if args.same_domain and host(url) not in seed_hosts:
                    continue
                if args.respect_robots and not robots.allowed(url):
                    print(f"SKIP robots {url}", file=sys.stderr)
                    continue

                try:
                    response = client.get(url)
                    fetched += 1
                except Exception as exc:
                    print(f"FAIL fetch {url}: {exc}", file=sys.stderr)
                    continue

                ctype = response.headers.get("content-type", "").lower()
                if response.status_code >= 400 or "text/html" not in ctype:
                    continue

                title, text, links = visible_text_and_links(response.text, str(response.url))
                keep, keywords = should_keep_page(title, text, str(response.url), args.min_chars, args.min_keywords)
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if keep and text_hash not in emitted_hashes:
                    emitted_hashes.add(text_hash)
                    item = CrawlItem(
                        url=str(response.url),
                        title=title,
                        text=text[: args.max_text_chars],
                        text_hash=text_hash,
                        matched_keywords=keywords,
                        collected_at=datetime.now(timezone.utc).isoformat(),
                        access_basis=args.access_basis,
                    )
                    out.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
                    out.flush()
                    saved += 1
                    print(f"SAVED {saved}: {item.title or item.url} keywords={','.join(keywords[:5])}")
                    if args.send_collector:
                        try:
                            post_to_collector(item, args.collector_url)
                        except Exception as exc:
                            print(f"FAIL collector {item.url}: {exc}", file=sys.stderr)

                if depth < args.max_depth:
                    ranked = sorted(
                        (link for link in links if link not in seen),
                        key=lambda link: link_priority(link),
                        reverse=True,
                    )
                    for link in ranked[: args.max_links_per_page]:
                        if link_priority(link) >= 0:
                            queue.append((link, depth + 1))

                if args.delay > 0:
                    time.sleep(args.delay)

    print(json.dumps({"fetched": fetched, "saved": saved, "output": str(output_path)}, ensure_ascii=False))
    return 0 if saved or fetched else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="httpx + BeautifulSoup 公开/授权简历静态页爬虫")
    parser.add_argument("--seed", action="append", default=[], help="起始 URL，可重复")
    parser.add_argument("--seed-file", default="", help="起始 URL 文件，一行一个")
    parser.add_argument("--output", default="data/public_resume_crawl.jsonl")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--max-links-per-page", type=int, default=30)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--min-keywords", type=int, default=2)
    parser.add_argument("--max-text-chars", type=int, default=120_000)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--access-basis", default="public", choices=["public", "user_authorized", "candidate_provided"])
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--respect-robots", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--send-collector", action="store_true", help="同步 POST 到 reloop /api/capture")
    parser.add_argument("--collector-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    return crawl(args)


if __name__ == "__main__":
    raise SystemExit(main())
