"""语音/文本指令 → 意图解析。规则在 config/commands.yaml 中配置。

匹配方式：
- keyword：文本包含任一关键词即命中（子串匹配）
- regex：  按正则提取参数（支持 match/fullmatch/search）
按配置顺序 + order 优先级依次尝试，先命中的优先。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from ..music.pinyin_match import similarity

log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


@dataclass
class Command:
    intent: str
    args: dict = field(default_factory=dict)


@dataclass
class Rule:
    intent: str
    rule_type: str  # keyword / regex
    keywords: List[str] = field(default_factory=list)
    regex: Optional[str] = None
    match: str = "search"  # fullmatch / match / search
    args_map: Dict[str, str] = field(default_factory=dict)
    args_transform: Dict[str, str] = field(default_factory=dict)
    static_args: Dict[str, str] = field(default_factory=dict)
    order: int = 100


def _load_rules(path: Optional[str] = None) -> List[Rule]:
    """从 commands.yaml 加载指令规则。"""
    path = path or os.path.join(PROJECT_ROOT, "config", "commands.yaml")
    if not os.path.exists(path):
        log.warning("指令配置文件缺失: %s", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        log.warning("指令配置文件解析失败: %s", path, exc_info=True)
        return []
    rules = []
    for item in data.get("commands", []):
        rules.append(
            Rule(
                intent=item.get("intent", "unknown"),
                rule_type=item.get("type", "keyword"),
                keywords=list(item.get("keywords", [])),
                regex=item.get("regex"),
                match=item.get("match", "search"),
                args_map=dict(item.get("args_map", {})),
                args_transform=dict(item.get("args_transform", {})),
                static_args=dict(item.get("static_args", {})),
                order=int(item.get("order", 100)),
            )
        )
    # 按 order 升序，同 order 保持配置顺序
    rules.sort(key=lambda r: r.order)
    return rules


def _strip(text: str) -> str:
    """去掉书名号/引号/空格/标点等干扰。"""
    for ch in "《》「」“”\"'『』，。、,.!?！？ \t":
        text = text.replace(ch, "")
    return text.strip()


# 指令开头的语气词/噪声（ASR 常误识别出的前缀）
_PREFIX_NOISE = re.compile(
    r"^(?:好的|a|a的|嗯|恩|那个|那个的|额|呃|哦|喔|然后|就是说|好|你|你能|帮我帮我|给我|请请|麻烦麻烦"
    r"|小爱同学|你好军哥|小艺小艺|小米小米|你好西西|你好问问|你好小智|蛋哥蛋哥|林美丽|你好嘛)"
    r"[，。、,.\s]*"
)


def _fold_repeats(text: str) -> str:
    """折叠连续重复字符：'随随机播' → '随机播'（ASR 常见叠字）。"""
    out: List[str] = []
    for ch in text:
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


# 中文数字 → int（支持 零~九、十、百、两）
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(text: str) -> int:
    """把中文数字转 int；已是阿拉伯数字则直接 int。如 六十→60、一百→100、二十一→21。"""
    s = text.strip()
    if s.isdigit():
        return int(s)
    if not s:
        return 0
    if "百" in s:
        head, _, rest = s.partition("百")
        v = _CN_DIGITS.get(head, 1) * 100
        return v + (cn_to_int(rest) if rest else 0)
    if "十" in s:
        head, _, rest = s.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        return tens * 10 + (_CN_DIGITS.get(rest, 0) if rest else 0)
    return _CN_DIGITS.get(s, 0)


_CN_NUM_STR = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def int_to_cn(n: int) -> str:
    """把 0-999 的整数转中文读法，供 TTS 播报：60→六十、100→一百、21→二十一。"""
    n = int(n)
    if n < 0:
        return "负" + int_to_cn(-n)
    if n < 10:
        return _CN_NUM_STR[n]
    if n < 20:
        return "十" + (_CN_NUM_STR[n % 10] if n % 10 else "")
    if n < 100:
        t, r = divmod(n, 10)
        return _CN_NUM_STR[t] + "十" + (_CN_NUM_STR[r] if r else "")
    if n < 1000:
        h, r = divmod(n, 100)
        s = _CN_NUM_STR[h] + "百"
        if r:
            if r < 10:
                s += "零" + _CN_NUM_STR[r]
            elif r % 10 == 0:
                s += _CN_NUM_STR[r // 10] + "十"
            else:
                s += _CN_NUM_STR[r // 10] + "十" + _CN_NUM_STR[r % 10]
        return s
    return str(n)


# 关键词拼音模糊匹配阈值：应对同音字/丢字/叠字（如 随机播≈随机播放）
_FUZZY_THRESHOLD = 0.7


def _clean(text: str) -> str:
    """去掉开头语气词/噪声前缀，提高指令匹配率。"""
    while True:
        m = _PREFIX_NOISE.match(text)
        if not m or m.group(0) == "":
            break
        text = text[m.end():].lstrip()
        if not text:
            break
    return text.strip()


_RULES: List[Rule] = []


def _get_rules() -> List[Rule]:
    global _RULES
    if not _RULES:
        _RULES = _load_rules()
    return _RULES


def parse_command(text: str, rules: Optional[List[Rule]] = None) -> Command:
    """把识别文本解析为 (intent, args)。

    两遍匹配：
    1. 精确匹配（关键词子串 + 正则），按规则顺序，先命中先返回；
    2. 若全部失败，再做拼音模糊兜底（应对同音字/叠字/丢字）。
    这样精确规则不会被模糊规则抢先，避免误判（如 顺序播放≠随机播放）。
    """
    t = _clean(text.strip())
    if not t:
        return Command("unknown", {})
    rules = rules or _get_rules()
    for rule in rules:
        cmd = _match_rule(rule, t, use_fuzzy=False)
        if cmd is not None:
            return cmd
    for rule in rules:
        cmd = _match_rule(rule, t, use_fuzzy=True)
        if cmd is not None:
            return cmd
    return Command("unknown", {})


def _match_rule(rule: Rule, text: str, use_fuzzy: bool = False) -> Optional[Command]:
    """尝试用一条规则匹配；命中返回 Command，否则 None。"""
    if rule.rule_type == "keyword":
        lt = _fold_repeats(text)
        for kw in rule.keywords:
            if kw in lt:
                return Command(rule.intent, dict(rule.static_args))
        if use_fuzzy:
            # 拼音模糊兜底：应对同音字/丢字/叠字；仅对较长关键词启用避免误伤。
            # 首字约束：同字或拼音相似（如 随≈谁）才继续，避免"当前歌单"误匹配
            # "现在歌单"这类首字差异大的近义文本。
            for kw in rule.keywords:
                if len(kw) < 3 or len(lt) < 1:
                    continue
                if kw[0] == lt[0] or similarity(kw[0], lt[0]) >= 0.5:
                    if similarity(kw, lt) >= _FUZZY_THRESHOLD:
                        return Command(rule.intent, dict(rule.static_args))
        return None
    if rule.rule_type == "regex" and rule.regex:
        try:
            if rule.match == "fullmatch":
                m = re.fullmatch(rule.regex, text)
            elif rule.match == "match":
                m = re.match(rule.regex, text)
            else:
                m = re.search(rule.regex, text)
        except re.error:  # noqa: BLE001
            log.warning("指令正则错误: %s", rule.regex, exc_info=True)
            return None
        if m:
            args = dict(rule.static_args)
            for dst, src in rule.args_map.items():
                raw = m.group(src)
                val = _strip(raw) if raw else raw
                # 纯数字参数自动转 int（如播放第3首 / 音量调到60）
                if isinstance(val, str) and val.lstrip("-").isdigit():
                    val = int(val)
                # 配置的取值变换（如 int_minus_1：第N首 → 0 基索引 N-1；cn_number：中文数字→int）
                transform = rule.args_transform.get(dst)
                if transform == "int_minus_1":
                    val = int(val) - 1
                elif transform == "cn_number":
                    val = cn_to_int(str(val))
                args[dst] = val
            return Command(rule.intent, args)
    return None


def reload_rules() -> None:
    """重新加载指令配置（改配置后调用）。"""
    global _RULES
    _RULES = _load_rules()


if __name__ == "__main__":  # 调试：python -m app.commands.parser
    import sys

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        cmd = parse_command(line)
        print(f"{line!r} -> {cmd.intent} {cmd.args}")
