"""拼音转换与模糊匹配：应对中文歌名的同音字与识别误差。"""
from __future__ import annotations

from typing import List, Tuple

try:
    from pypinyin import lazy_pinyin

    _HAS_PYPINYIN = True
except Exception:  # pragma: no cover - 依赖未安装时的兜底
    _HAS_PYPINYIN = False


def to_pinyin(text: str) -> str:
    """转换为不带声调的拼音串（小写），用于匹配。无 pypinyin 时回退原文本。"""
    if not text:
        return ""
    if _HAS_PYPINYIN:
        return "".join(lazy_pinyin(text)).lower()
    return text.lower()


def levenshtein(a: str, b: str) -> int:
    """编辑距离（支持任意字符）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, 1):
        cur = [i]
        for j, ch_b in enumerate(b, 1):
            cur.append(
                min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ch_a != ch_b))
            )
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """0~1 相似度：拼音编辑距离归一化 + 前缀加分。"""
    if not a or not b:
        return 0.0
    pa, pb = to_pinyin(a), to_pinyin(b)
    if not pa or not pb:
        return 0.0
    if pa == pb:
        return 1.0
    # 子串匹配：查询词是候选的子串（如"红玫瑰" ⊂ "陈奕迅-红玫瑰"）→ 高分
    if pa in pb:
        return 0.98
    if pb in pa:
        return 0.98
    dist = levenshtein(pa, pb)
    max_len = max(len(pa), len(pb)) or 1
    score = 1.0 - dist / max_len
    if pb.startswith(pa) or pa.startswith(pb):
        score += 0.05
    return max(0.0, min(1.0, score))


def best_match(
    query: str,
    candidates: List[str],
    threshold: float = 0.6,
    top_n: int = 3,
) -> List[Tuple[str, float]]:
    """返回按相似度降序的 (候选, 分数) 列表，过滤低于阈值者。"""
    scored = [(c, similarity(query, c)) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [(c, s) for c, s in scored if s >= threshold][:top_n]
