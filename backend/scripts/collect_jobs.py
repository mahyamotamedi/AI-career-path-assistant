"""Collect job postings from all sources into data/jobs/postings.jsonl.

Run from backend/:  python -m scripts.collect_jobs
Add a new source by creating app/jobs/collector/sources/<name>.py with SOURCE and
fetch(fetcher, cap) and listing it in SOURCES below. Needs >= 50 postings from >= 2 sources.
"""
import logging
import re
from collections import Counter

from app.careers.taxonomy import get_taxonomy
from app.jobs import dedup, store
from app.jobs.collector.base import PoliteFetcher
from app.jobs.collector.sources import jobinja, jobvision
from app.jobs.normalize import map_text_skills, normalize_text
from app.schemas import JobPosting

SOURCES = [jobinja, jobvision]
MIN_TOTAL = 50
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


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    fetcher = PoliteFetcher()
    results: dict[str, list[JobPosting]] = {}
    for src in SOURCES:
        try:
            got = src.fetch(fetcher)
        except Exception as e:  # one broken source must not stop the run
            print(f"[fail] {src.SOURCE}: {type(e).__name__}: {e}")
            got = []
        print(f"[{'ok' if got else 'EMPTY'}] {src.SOURCE}: {len(got)} postings")
        results[src.SOURCE] = got
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
    main()
