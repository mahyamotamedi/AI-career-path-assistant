| Method | P@5 | nDCG@10 |
|---|---|---|
| BM25 baseline | 1.000 | 0.890 |
| Hybrid (ours) [no embeddings: skills+seniority] | 0.600 | 0.580 |
| Skills only (ablation) | 0.600 | 0.559 |

3 synthetic resumes x 80 labelled postings; embeddings NOT available (no gateway key): hybrid = skill overlap + seniority fit only.

Per resume (P@5 / nDCG@10):

| Resume | #relevant | BM25 baseline | Hybrid (ours) [no embeddings: skills+seniority] | Skills only (ablation) |
|---|---|---|---|---|
| r1_data_analyst_junior | 8 | 1.00 / 0.82 | 0.60 / 0.50 | 0.60 / 0.49 |
| r2_backend_python_mid | 9 | 1.00 / 0.85 | 0.20 / 0.37 | 0.20 / 0.33 |
| r3_digital_marketing_junior | 16 | 1.00 / 1.00 | 1.00 / 0.86 | 1.00 / 0.86 |
