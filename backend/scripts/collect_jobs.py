"""Collect job postings from all sources into data/jobs/postings.jsonl.

Run from backend/:  python -m scripts.collect_jobs [--incremental]
--incremental: upsert into the existing postings (listing pages re-fetched after 1 h, detail pages
from cache), keep a failing source's old postings, drop postings older than 60 days.
Add a new source by creating app/jobs/collector/sources/<name>.py with SOURCE and
fetch(fetcher, cap) and listing it in SOURCES below. Needs >= 50 postings from >= 2 sources.
"""
import logging
import os
import re
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta

from app.careers.taxonomy import get_taxonomy
from app.config import settings
from app.jobs import dedup, store
from app.jobs.collector.base import PoliteFetcher
from app.jobs.collector.sources import jobinja, jobvision
from app.jobs.normalize import map_text_skills, normalize_text
from app.schemas import JobPosting

SOURCES = [jobinja, jobvision]
MIN_TOTAL = 50
MAX_AGE_DAYS = 60  # incremental refresh drops postings published longer ago than this
MAX_PER_SOURCE = 200
LOCK_STALE_S = 2 * 3600
_STOP = set("و در به از با که را این یا برای تا بر یک هر های می است باشد شده یا نیز دارای حداقل مانند آشنایی تسلط تجربه کار کاری سال سابقه توانایی مورد نیاز the and of to in a with for or on we is this will be are that work team maintain".split())


def unmapped_phrases(postings: list[JobPosting], top: int = 30) -> list[tuple[str, int]]:
    """Requirement phrases/words that map to no taxonomy concept (candidates for new aliases)."""
    tax = get_taxonomy()
    counts: Counter[str] = Counter()
    for p in postings:
        seen: set[str] = set()
        for line in p.requirements:
            if map_text_skills([line], tax):
                continue
            n = normalize_text(line)
            words = re.findall(r"[\w+#./]+", n)
            # short tag-like lines whole; from long sentences only Latin tech tokens (Persian words are noise)
            cands = [n] if len(words) <= 4 else [w for w in words if len(w) >= 2 and w.isascii() and w not in _STOP]
            seen.update(c for c in cands if c)
        counts.update(seen)  # count each phrase once per posting
    return counts.most_common(top)


def summarize(postings: list[JobPosting]) -> None:
    print("\n--- summary ---")
    print("per source   :", dict(Counter(p.source for p in postings)))
    print("per seniority:", dict(Counter(p.seniority or "unknown" for p in postings)))
    mapped = sum(1 for p in postings if p.skill_ids)
    print(f"with >=1 skill_id: {mapped}/{len(postings)}")
    print("top unmapped requirement phrases/words:")
    for phrase, n in unmapped_phrases(postings):
        print(f"  {n:3d}  {phrase}")


def merge_incremental(
    existing: list[JobPosting], fresh: dict[str, list[JobPosting]], today: date | None = None,
    max_age_days: int = MAX_AGE_DAYS,
) -> list[JobPosting]:
    """Upsert fresh postings by id into the existing ones.

    A source that returned nothing (blocked, failed) keeps its old postings. Postings published
    more than `max_age_days` ago are dropped (expiry); each source keeps at most MAX_PER_SOURCE
    (newest first). The result is deduplicated across sources.
    """
    cutoff = ((today or date.today()) - timedelta(days=max_age_days)).isoformat()
    by_id: dict[str, JobPosting] = {p.id: p for p in existing}
    for got in fresh.values():
        by_id.update({p.id: p for p in got})  # new data wins
    alive = [p for p in by_id.values() if not p.published_at or p.published_at >= cutoff]
    out: list[JobPosting] = []
    for source in dict.fromkeys(p.source for p in alive):
        mine = sorted((p for p in alive if p.source == source), key=lambda p: (p.published_at or "", p.id), reverse=True)
        out.extend(mine[:MAX_PER_SOURCE])
    return dedup.dedup(out)


@contextmanager
def collect_lock():
    """Single-writer lock file; a lock older than LOCK_STALE_S is treated as left by a crash."""
    path = settings.data_dir / "jobs" / ".collect.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > LOCK_STALE_S:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    os.close(fd)
    try:
        yield True
    finally:
        path.unlink(missing_ok=True)


def main(incremental: bool = False) -> None:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    fetcher = PoliteFetcher()
    previous = store.load_postings() if incremental else []
    results: dict[str, list[JobPosting]] = {}
    for src in SOURCES:
        try:
            got = src.fetch(fetcher)
        except Exception as e:  # one broken source must not stop the run
            print(f"[fail] {src.SOURCE}: {type(e).__name__}: {e}")
            got = []
        print(f"[{'ok' if got else 'EMPTY'}] {src.SOURCE}: {len(got)} postings")
        results[src.SOURCE] = got
    if incremental:
        merged = merge_incremental(previous, results)
        if not merged:
            print("Nothing to write; postings.jsonl left untouched.")
            return
        store.save_postings(merged)
        print(f"Incremental refresh: {len(previous)} -> {len(merged)} postings in {store.postings_path()}")
        summarize(merged)
        return
    postings = dedup.dedup([p for got in results.values() for p in got])
    empty = [s for s, got in results.items() if not got]
    if empty and len(postings) < MIN_TOTAL:  # a source is blocked: top up from the others
        for src in SOURCES:
            if results[src.SOURCE]:
                print(f"[top-up] {src.SOURCE}: raising cap to {MIN_TOTAL}")
                results[src.SOURCE] = src.fetch(fetcher, cap=MIN_TOTAL)
        postings = dedup.dedup([p for got in results.values() for p in got])
    if not postings:
        print("No postings collected; postings.jsonl left untouched.")
        return
    store.save_postings(postings)
    print(f"Wrote {len(postings)} postings to {store.postings_path()}")
    summarize(postings)


if __name__ == "__main__":
    with collect_lock() as acquired:
        if acquired:
            main(incremental="--incremental" in sys.argv)
        else:
            print("Another collection run holds the lock; skipping.")
