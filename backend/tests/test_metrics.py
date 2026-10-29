import math

from scripts.evaluate_ranking import ndcg_at_k, precision_at_k


def test_precision_at_5():
    assert precision_at_k(["a", "x", "b", "y", "z", "c"], {"a", "b", "c"}, 5) == 0.4  # hits at ranks 1 and 3


def test_ndcg_at_10_perfect_is_1():
    assert ndcg_at_k(["a", "b", "c", "x", "y"], {"a", "b", "c"}, 10) == 1.0


def test_ndcg_empty_relevant_is_0():
    assert ndcg_at_k(["a", "b"], set(), 10) == 0.0
    assert precision_at_k(["a", "b"], set(), 5) == 0.0


def test_ndcg_hand_computed():
    # relevant {a, b}; ranking x, a, y, b: DCG = 1/log2(3) + 1/log2(5); IDCG = 1/log2(2) + 1/log2(3)
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert math.isclose(ndcg_at_k(["x", "a", "y", "b"], {"a", "b"}, 10), dcg / idcg)  # ~= 0.6509


def test_ndcg_idcg_capped_at_k_and_ignores_beyond_k():
    rel = {f"r{i}" for i in range(20)}
    assert ndcg_at_k([f"r{i}" for i in range(10)], rel, 10) == 1.0  # 20 relevant but only 10 slots
    assert ndcg_at_k(["x"] * 10 + ["r0"], {"r0"}, 10) == 0.0  # hit beyond k does not count


def test_eval_data_is_consistent():
    from scripts.evaluate_ranking import load_eval
    postings, resumes, relevant = load_eval()
    ids = {p.id for p in postings}
    assert len(postings) >= 50 and len(resumes) == 3
    for rid in resumes:
        assert len(relevant[rid]) >= 3 and relevant[rid] <= ids
