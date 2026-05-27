"""Word cloud helper for the dashboard — phrase extraction + image rendering.

Lives outside app.py so app.py stays focused on layout. Builds a frequency
map of unigrams + bigrams from article titles and Vietnamese summaries,
drops stopwords and the project's own search keywords (otherwise "vay mua nhà"
would dominate every cloud), and hands the result to the wordcloud library.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from typing import Iterable

from matplotlib.colors import LinearSegmentedColormap
from wordcloud import WordCloud

# KBank-Vietnam green ramp for the word cloud. Avoid matplotlib's built-in
# "Greens" — it bottoms out near-white and the lightest words go invisible on
# the white background. Our ramp starts at primary_light so every word stays
# readable.
_KBANK_GREEN_CMAP = LinearSegmentedColormap.from_list(
    "kbank_green", ["#3FAE52", "#138F2D", "#0E6B22", "#094D18"]
)

# Common Vietnamese function words. Kept here (not in keywords.yaml) because
# they're a property of the language, not of the home-loan domain.
_VN_STOPWORDS = {
    "của", "là", "và", "có", "được", "ở", "các", "một", "để", "đã", "không",
    "cho", "người", "với", "từ", "này", "đó", "vào", "ra", "lên", "sẽ", "đi",
    "tại", "theo", "làm", "như", "hay", "còn", "nhưng", "hơn", "khi", "nếu",
    "vì", "do", "sau", "trước", "hiện", "rất", "đang", "đến", "bị", "mà",
    "thì", "trong", "trên", "dưới", "về", "đây", "kia", "ấy", "cũng", "lại",
    "chỉ", "đều", "cả", "mỗi", "nhiều", "ít", "lớn", "nhỏ", "ngày", "tháng",
    "năm", "giờ", "phút", "lần", "thứ", "số", "khoảng", "gần", "xa", "bằng",
    "qua", "nên", "phải", "cần", "muốn", "biết", "thấy", "nói", "đó", "đấy",
    "à", "ạ", "nhé", "nha", "à", "hả", "ư", "ơi",
}

_EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "in", "of", "for", "with",
    "on", "at", "from", "by", "this", "that", "these", "those", "is", "are",
    "was", "were", "be", "been", "being", "has", "have", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "can", "shall",
    "must", "as", "if", "than", "then", "so", "such", "no", "not", "only",
    "own", "same", "very", "just", "now", "up", "down", "out", "over", "under",
}

_STOPWORDS = _VN_STOPWORDS | _EN_STOPWORDS

# Strip punctuation but keep Vietnamese letters with diacritics
_TOKEN_RE = re.compile(r"[^\w\sÀ-ỹà-ỹ]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    text = _TOKEN_RE.sub(" ", text.lower())
    return [w for w in text.split() if len(w) > 1 and w not in _STOPWORDS]


# Generic home-loan vocabulary that would dominate every cloud regardless of
# what the conversation is actually about. Kept narrow on purpose — domain
# words like "lãi suất" stay in because their modifiers ("giảm", "tăng",
# "ưu đãi") are exactly the signal we want to see.
_GENERIC_BLOCKED = {
    "vay", "mua", "nhà", "vay mua", "mua nhà", "vay nhà", "cho vay",
    "căn hộ", "chung cư", "bất động sản", "nhà đất", "thế chấp",
    "tín dụng", "sổ đỏ", "sổ hồng", "loan", "home", "house",
}


def _extract_phrases(texts: Iterable[str], blocklist: set[str]) -> Counter:
    """Return Counter of unigrams + bigrams across all texts.

    A bigram is dropped if either the full phrase is in blocklist, or if
    both individual words are blocked (e.g. "vay mua" — both "vay" and
    "mua" are generic, the combo carries no new signal).
    """
    counter: Counter = Counter()
    word_block = {w for w in blocklist if " " not in w}

    for text in texts:
        if not text:
            continue
        words = _tokenize(text)

        for w in words:
            if w in word_block:
                continue
            counter[w] += 1

        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            phrase = f"{w1} {w2}"
            if phrase in blocklist:
                continue
            if w1 in word_block and w2 in word_block:
                continue
            counter[phrase] += 1
    return counter


def _build_blocklist(home_loan_cfg: dict) -> set[str]:
    """Curated generic words + the long keyword phrases from keywords.yaml.

    Note: forum_keywords is intentionally NOT included — it contains short
    domain phrases like "lãi suất" and "thế chấp" that we WANT to see
    surfaced in the cloud (their modifiers are the actual signal).
    """
    blocklist: set[str] = set(_GENERIC_BLOCKED)
    for group in ("vietnamese", "interest_rate", "credit", "promotions"):
        for kw in home_loan_cfg.get(group, []):
            blocklist.add(kw.lower())
    return blocklist


def render_png(
    texts: Iterable[str],
    home_loan_cfg: dict,
    width: int = 900,
    height: int = 380,
    max_phrases: int = 80,
) -> bytes | None:
    """Build a word cloud PNG from the given texts. Returns None if no phrases."""
    blocklist = _build_blocklist(home_loan_cfg)
    freq = _extract_phrases(texts, blocklist)

    if not freq:
        return None

    top = dict(freq.most_common(max_phrases))

    wc = WordCloud(
        width=width,
        height=height,
        background_color="white",
        colormap=_KBANK_GREEN_CMAP,
        prefer_horizontal=0.9,
        relative_scaling=0.4,
        min_font_size=10,
    ).generate_from_frequencies(top)

    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    return buf.getvalue()
