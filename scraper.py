#!/usr/bin/env python3
"""
Scraper vybraných vláken phpBB fóra MobilMania -> RSS feed.

Logika:
  1. Pro každé vlákno z config.yml zjistí poslední stránku (pagination).
  2. Stáhne posledních N stránek (settings.pages_back).
  3. Naparsuje příspěvky (id, autor, čas, text, odkaz).
  4. Přes state.json si pamatuje poslední zpracované post ID pro každé
     vlákno -> zpracuje jen nové příspěvky.
  5. Nové položky přidá do items.json (rolling zásobník) a z něj
     vygeneruje feed.xml, takže feed nikdy "nezmizí" ani ve dnech,
     kdy nic nového nepřibude.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

ROOT = Path(__file__).parent
UA = "Mozilla/5.0 (X11; Linux x86_64) personal-rss-scraper/1.0 (1x denne, osobni pouziti)"

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "cs,en;q=0.8"})


def load_config():
    with open(ROOT / "config.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch(url: str, delay: float) -> BeautifulSoup | None:
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! Chyba při stahování {url}: {e}", file=sys.stderr)
        return None
    finally:
        time.sleep(delay)
    return BeautifulSoup(r.text, "html.parser")


def find_last_start(soup: BeautifulSoup) -> int:
    """Z pagination odkazů zjistí nejvyšší hodnotu start= (poslední stránka)."""
    max_start = 0
    for a in soup.select("div.pagination a[href*='start=']"):
        m = re.search(r"start=(\d+)", a.get("href", ""))
        if m:
            max_start = max(max_start, int(m.group(1)))
    return max_start


def posts_per_page(soup: BeautifulSoup) -> int:
    """Odhad počtu příspěvků na stránku z pagination kroků, fallback 40."""
    starts = sorted({
        int(m.group(1))
        for a in soup.select("div.pagination a[href*='start=']")
        if (m := re.search(r"start=(\d+)", a.get("href", "")))
    })
    if len(starts) >= 1 and starts[0] > 0:
        return starts[0]
    return 40


def parse_posts(soup: BeautifulSoup, thread: dict, base_url: str) -> list[dict]:
    """Vytáhne příspěvky ze stránky vlákna."""
    items = []
    for div in soup.select("div.post"):
        pid_attr = div.get("id", "")
        m = re.match(r"p(\d+)", pid_attr)
        if not m:
            continue
        pid = int(m.group(1))

        author_el = div.select_one(".author strong, .author a.username, .author a.username-coloured")
        author = author_el.get_text(strip=True) if author_el else "neznámý"

        # čas: novější phpBB má <time datetime=...>, starší jen text v .author
        published = None
        time_el = div.select_one(".author time[datetime]")
        if time_el:
            try:
                published = datetime.fromisoformat(time_el["datetime"])
            except ValueError:
                pass
        if published is None:
            published = datetime.now(timezone.utc)

        content_el = div.select_one("div.content")
        if not content_el:
            continue
        # citace nechat, jen zkrátit dlouhé posty pro feed
        text_html = str(content_el)
        text_plain = content_el.get_text(" ", strip=True)

        items.append({
            "id": pid,
            "thread_id": thread["id"],
            "thread_name": thread.get("name", str(thread["id"])),
            "author": author,
            "published": published.isoformat(),
            "link": urljoin(base_url, f"/viewtopic.php?p={pid}#p{pid}"),
            "title": f"[{thread.get('name', thread['id'])}] {author}: {text_plain[:90]}",
            "html": text_html,
        })
    return items


def scrape_thread(thread: dict, cfg: dict, last_seen: int) -> list[dict]:
    base = thread["base_url"]
    delay = cfg["settings"]["delay_seconds"]
    pages_back = cfg["settings"]["pages_back"]

    first_url = urljoin(base, f"/viewtopic.php?t={thread['id']}")
    soup = fetch(first_url, delay)
    if soup is None:
        return []

    last_start = find_last_start(soup)
    per_page = posts_per_page(soup)

    # stránky ke stažení: poslední + (pages_back - 1) před ní
    starts = sorted({max(0, last_start - i * per_page) for i in range(pages_back)})

    all_posts: dict[int, dict] = {}
    for start in starts:
        if start == 0 and last_start == 0:
            page_soup = soup  # jednostránkové vlákno – už máme
        else:
            url = urljoin(base, f"/viewtopic.php?t={thread['id']}&start={start}")
            page_soup = fetch(url, delay)
            if page_soup is None:
                continue
        for p in parse_posts(page_soup, thread, base):
            all_posts[p["id"]] = p

    new = [p for p in all_posts.values() if p["id"] > last_seen]
    new.sort(key=lambda p: p["id"])
    print(f"  Vlákno {thread['id']}: {len(all_posts)} příspěvků načteno, {len(new)} nových")
    return new


def build_feed(items: list[dict], cfg: dict):
    fg = FeedGenerator()
    fg.id("urn:forum-rss:combined-feed")
    fg.title(cfg["feed"]["title"])
    fg.description(cfg["feed"]["description"])
    fg.language(cfg["feed"]["language"])
    fg.link(href="https://forum.mobilmania.zive.cz", rel="alternate")

    # RSS čtečky berou položky v pořadí; feedgen je vypisuje obráceně,
    # proto řadíme vzestupně, aby nejnovější skončily nahoře
    for it in sorted(items, key=lambda p: p["id"]):
        fe = fg.add_entry()
        fe.id(it["link"])
        fe.title(it["title"])
        fe.link(href=it["link"])
        fe.author(name=it["author"])
        fe.content(it["html"], type="CDATA")
        try:
            fe.published(datetime.fromisoformat(it["published"]))
        except ValueError:
            fe.published(datetime.now(timezone.utc))

    fg.rss_file(str(ROOT / cfg["settings"]["feed_file"]), pretty=True)


def main():
    cfg = load_config()
    s = cfg["settings"]
    state = load_json(ROOT / s["state_file"], {})
    items = load_json(ROOT / s["items_file"], [])

    total_new = 0
    for thread in cfg["threads"]:
        # klíč kombinuje doménu + id, aby se stejné ID na dvou fórech nepletlo
        tid = f"{thread['base_url']}::{thread['id']}"
        last_seen = state.get(tid, 0)
        new_posts = scrape_thread(thread, cfg, last_seen)
        if new_posts:
            state[tid] = max(p["id"] for p in new_posts)
            items.extend(new_posts)
            total_new += len(new_posts)

    # zásobník omezit na max_feed_items nejnovějších
    items.sort(key=lambda p: p["id"])
    items = items[-s["max_feed_items"]:]

    save_json(ROOT / s["state_file"], state)
    save_json(ROOT / s["items_file"], items)
    build_feed(items, cfg)

    print(f"Hotovo: {total_new} nových příspěvků, feed má {len(items)} položek.")


if __name__ == "__main__":
    main()
