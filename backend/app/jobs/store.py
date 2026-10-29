import json
import os
from pathlib import Path

from app.config import settings
from app.schemas import JobPosting


def postings_path() -> Path:
    return settings.data_dir / "jobs" / "postings.jsonl"


def load_postings() -> list[JobPosting]:
    path = postings_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [JobPosting(**json.loads(line)) for line in f if line.strip()]


def save_postings(postings: list[JobPosting]) -> None:
    """Atomic write: a crash mid-write leaves the previous postings.jsonl intact."""
    path = postings_path()
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for p in postings:
            f.write(p.model_dump_json() + "\n")
    os.replace(tmp, path)
