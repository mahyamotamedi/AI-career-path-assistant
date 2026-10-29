"""Evaluate our ranker vs the BM25 baseline on the labelled set.  Run: python -m scripts.evaluate_ranking

Data (all under data/eval/, frozen so later job refreshes cannot change the numbers):
  postings_snapshot.jsonl   copy of data/jobs/postings.jsonl (scripts/snapshot_eval_postings.py)
  resumes/*.json            3 synthetic ResumeProfile files (fictional people)
  labels.csv                resume_id,posting_id,relevant,note  for every resume x posting

Metrics, per resume then averaged over resumes (binary relevance, full snapshot ranked, no filters):
  Precision@5 = (# relevant postings among the top 5 ranked) / 5
  nDCG@10     = DCG@10 / IDCG@10, DCG = sum_{i=1..10} rel_i / log2(i + 1); IDCG = DCG of the ideal
                ordering (min(#relevant, 10) hits first); 0 when nothing is relevant.

LABELLING RULES (independent of the rankers; applied to the posting TITLE and SENIORITY only,
never to skill_ids, ranker scores or embeddings; see FAMILY/ADJACENT in snapshot_eval_postings.py):
  A posting is relevant to a resume iff
    (a) it is in the resume's role family: r1 data analyst / BI (Data Analyst, تحلیلگر داده, ...),
        r2 Python / Django backend developer, r3 SEO / digital / growth marketing; AND
    (b) its seniority is the resume's level (r1 junior, r2 mid, r3 junior) or one step away,
        or the posting has no seniority.
  Everything else is not relevant. Adjacent families (data engineer, ML, DevOps, finance analyst,
  product manager) and same-family postings two seniority levels away are labelled 0 and marked
  "borderline" in the note column so a human can flip them in labels.csv.
Weights are the config defaults; they were NOT tuned on these resumes.
"""
import csv
import json
import logging
import math
from collections import defaultdict

from app.config import settings
from app.jobs import ranking
from app.schemas import JobPosting, ResumeProfile

EVAL = settings.data_dir / "eval"
SESSION = "eval"


def precision_at_k(ranked_ids: list[str], relevant: set[str], k: int = 5) -> float:
    return sum(1 for i in ranked_ids[:k] if i in relevant) / k


def ndcg_at_k(ranked_ids: list[str], relevant: set[str], k: int = 10) -> float:
    if not relevant:
        return 0.0
    dcg = sum(1 / math.log2(i + 2) for i, pid in enumerate(ranked_ids[:k]) if pid in relevant)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / idcg


def load_eval() -> tuple[list[JobPosting], dict[str, ResumeProfile], dict[str, set[str]]]:
    postings = [JobPosting(**json.loads(l)) for l in (EVAL / "postings_snapshot.jsonl").read_text("utf-8").splitlines() if l.strip()]
    resumes = {p.stem: ResumeProfile(**json.loads(p.read_text("utf-8"))) for p in sorted((EVAL / "resumes").glob("*.json"))}
    relevant: dict[str, set[str]] = defaultdict(set)
    with (EVAL / "labels.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["relevant"] == "1":
                relevant[row["resume_id"]].add(row["posting_id"])
    return postings, resumes, relevant


def _with_weights(**w):
    class Ctx:
        def __enter__(self):
            self.old = {k: getattr(settings, k) for k in w}
            for k, v in w.items():
                setattr(settings, k, v)

        def __exit__(self, *a):
            for k, v in self.old.items():
                setattr(settings, k, v)
    return Ctx()


def run() -> dict:
    postings, resumes, relevant = load_eval()
    n = len(postings)
    have_emb = all(ranking._embed_scores(SESSION, r, postings) is not None for r in resumes.values())
    methods: dict[str, callable] = {
        "BM25 baseline": lambda r: ranking.baseline_rank(r, postings, n),
        "Hybrid (ours)" + ("" if have_emb else " [no embeddings: skills+seniority]"): lambda r: ranking.hybrid_rank(SESSION, r, postings, n),
    }

    def skills_only(r):
        with _with_weights(w_embedding=0.0, w_seniority=0.0):
            return ranking.hybrid_rank(SESSION, r, postings, n)

    def emb_only(r):
        with _with_weights(w_skill_overlap=0.0, w_seniority=0.0):
            return ranking.hybrid_rank(SESSION, r, postings, n)

    methods["Skills only (ablation)"] = skills_only
    if have_emb:
        methods["Embeddings only (ablation)"] = emb_only
    results: dict = {"have_embeddings": have_emb, "n_postings": n, "methods": {}, "tops": {}}
    for name, fn in methods.items():
        per = {}
        for rid, r in resumes.items():
            ranked = [m.posting.id for m in fn(r)]
            per[rid] = (precision_at_k(ranked, relevant[rid], 5), ndcg_at_k(ranked, relevant[rid], 10))
            results["tops"].setdefault(rid, {})[name] = [(m.posting.id, m.posting.title) for m in fn(r)[:5]]
        results["methods"][name] = per
    results["relevant"] = {k: sorted(v) for k, v in relevant.items()}
    return results


def render(res: dict) -> str:
    out = []
    avg = lambda per, i: sum(v[i] for v in per.values()) / len(per)
    out += ["| Method | P@5 | nDCG@10 |", "|---|---|---|"]
    for name, per in res["methods"].items():
        out.append(f"| {name} | {avg(per, 0):.3f} | {avg(per, 1):.3f} |")
    out += ["", f"{len(next(iter(res['methods'].values())))} synthetic resumes x {res['n_postings']} labelled postings; "
            f"embeddings {'used' if res['have_embeddings'] else 'NOT available (no gateway key): hybrid = skill overlap + seniority fit only'}.", "",
            "Per resume (P@5 / nDCG@10):", "", "| Resume | #relevant | " + " | ".join(res["methods"]) + " |", "|---|---|" + "---|" * len(res["methods"])]
    for rid in next(iter(res["methods"].values())):
        cells = " | ".join(f"{m[rid][0]:.2f} / {m[rid][1]:.2f}" for m in res["methods"].values())
        out.append(f"| {rid} | {len(res['relevant'][rid])} | {cells} |")
    return "\n".join(out)


def main() -> None:
    logging.getLogger("app.jobs.ranking").setLevel(logging.ERROR)  # one summary line instead of one per call
    res = run()
    _, _, relevant = load_eval()
    table = render(res)
    print(table)
    (EVAL / "results.md").write_text(table + "\n", encoding="utf-8")
    print("\nTop 5 per method (✓ relevant, ✗ not):")
    for rid, by_method in res["tops"].items():
        print(f"\n[{rid}]")
        for name, top in by_method.items():
            print(f"  {name}")
            for pid, title in top:
                print(f"    {'✓' if pid in relevant[rid] else '✗'} {title[:60]}")


if __name__ == "__main__":
    main()
