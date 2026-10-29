"""Freeze the eval data: copy data/jobs/postings.jsonl -> data/eval/postings_snapshot.jsonl.

Run from backend/:  python -m scripts.snapshot_eval_postings [--labels]

--labels also (re)writes data/eval/labels.csv from the RULE LABELS below. The rules look ONLY at
the posting title and seniority (never at skill_ids, ranker scores or embeddings), so the labels
are independent of the rankers being evaluated. Edit labels.csv by hand to override a rule label;
re-running with --labels overwrites hand edits.
"""
import csv
import json
import re
import shutil
import sys

from app.config import settings
from app.jobs.normalize import normalize_text

EVAL = settings.data_dir / "eval"
LEVELS = {"junior": 0, "mid": 1, "senior": 2}

# role family per resume, matched on the normalised TITLE only
FAMILY = {
    "r1_data_analyst_junior": r"(تحلیل ?گر داده|تحلیل داده|data analyst|هوش تجاری|\bbi\b)",
    "r2_backend_python_mid": r"(python|پایتون|django|بک ?اند|back ?-?end)",
    "r3_digital_marketing_junior": r"(سئو|\bseo\b|دیجیتال ?مارکت|digital market|بازاریاب رشد|growth market)",
}
LEVEL = {"r1_data_analyst_junior": "junior", "r2_backend_python_mid": "mid", "r3_digital_marketing_junior": "junior"}
# adjacent families: NOT relevant, but flagged as borderline in the note so a human can flip them
ADJACENT = {
    "r1_data_analyst_junior": r"(data engineer|data scientist|machine learning|یادگیری|بینایی ماشین|computer vision|تحلیل مالی|تحلیلگر مالی|finance analyst|مالی)",
    "r2_backend_python_mid": r"(devops|دواپس|دوآپس|\bsre\b|data engineer|machine learning|یادگیری)",
    "r3_digital_marketing_junior": r"(مدیر محصول|product manager|لید محصول)",
}


def label(resume_id: str, title: str, seniority: str | None) -> tuple[int, str]:
    t = normalize_text(title)
    if not re.search(FAMILY[resume_id], t):
        adj = re.search(ADJACENT[resume_id], t)
        return 0, "borderline: adjacent role family" if adj else "other role family"
    if seniority is None:
        return 1, "same family; seniority unknown (allowed)"
    gap = abs(LEVELS[seniority] - LEVELS[LEVEL[resume_id]])
    if gap <= 1:
        return 1, "same family; seniority " + ("matches" if gap == 0 else "one step away")
    return 0, "borderline: same family but seniority two steps away"


def main() -> None:
    src = settings.data_dir / "jobs" / "postings.jsonl"
    EVAL.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, EVAL / "postings_snapshot.jsonl")
    postings = [json.loads(l) for l in (EVAL / "postings_snapshot.jsonl").read_text("utf-8").splitlines() if l.strip()]
    print(f"snapshot: {len(postings)} postings -> {EVAL / 'postings_snapshot.jsonl'}")
    if "--labels" in sys.argv:
        with (EVAL / "labels.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["resume_id", "posting_id", "relevant", "note"])
            for rid in FAMILY:
                for p in postings:
                    rel, note = label(rid, p["title"], p["seniority"])
                    w.writerow([rid, p["id"], rel, note])
        print("labels.csv written (rule labels; title + seniority only)")


if __name__ == "__main__":
    main()
