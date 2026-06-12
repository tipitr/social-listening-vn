"""top_phrases: rank recurring bigrams for the complaint-theme panel."""

from __future__ import annotations

from dashboard.wordcloud_view import top_phrases


def test_recurring_bigrams_ranked_first():
    texts = [
        "giải ngân chậm quá",
        "giải ngân chậm thật sự",
        "giải ngân chậm rồi",
        "hồ sơ phức tạp",
        "hồ sơ phức tạp ghê",
    ]
    result = top_phrases(texts, home_loan_cfg={}, k=3)
    phrases = [p for p, _ in result]
    assert any("giải ngân" in p or "ngân chậm" in p for p in phrases), \
        "the thrice-repeated 'giải ngân chậm' theme must surface"
    counts = [c for _, c in result]
    assert counts == sorted(counts, reverse=True), "must be ranked by count desc"


def test_one_off_phrases_are_dropped():
    texts = ["lãi suất tăng", "phí phạt cao"]   # each bigram appears once
    assert top_phrases(texts, home_loan_cfg={}, k=5) == []


def test_blocked_generic_phrases_excluded():
    # "vay mua" is in the generic blocklist — must never surface as a theme
    texts = ["vay mua nhà"] * 5
    phrases = [p for p, _ in top_phrases(texts, home_loan_cfg={}, k=5)]
    assert "vay mua" not in phrases
