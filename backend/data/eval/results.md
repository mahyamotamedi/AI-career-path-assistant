| Method | P@5 | nDCG@10 |
|---|---|---|
| BM25 baseline | 1.000 | 0.890 |
| Hybrid (ours) | 0.733 | 0.790 |
| Skills only (ablation) | 0.600 | 0.559 |
| Embeddings only (ablation) | 1.000 | 0.897 |

3 synthetic resumes x 80 labelled postings; embeddings used.

Per resume (P@5 / nDCG@10):

| Resume | #relevant | BM25 baseline | Hybrid (ours) | Skills only (ablation) | Embeddings only (ablation) |
|---|---|---|---|---|---|
| r1_data_analyst_junior | 8 | 1.00 / 0.82 | 0.60 / 0.76 | 0.60 / 0.49 | 1.00 / 0.84 |
| r2_backend_python_mid | 9 | 1.00 / 0.85 | 0.60 / 0.61 | 0.20 / 0.33 | 1.00 / 0.86 |
| r3_digital_marketing_junior | 16 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 0.86 | 1.00 / 1.00 |
