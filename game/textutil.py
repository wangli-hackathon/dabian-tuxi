"""摘要切句、稳定哈希、JSON 兜底解析。不引入分词依赖。"""

from __future__ import annotations

import hashlib
import json
import re


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def stable_index(key: str, size: int) -> int:
    """同一段文本永远落到同一个下标，演示模式靠这个保持可复现。"""
    if size <= 1:
        return 0
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;\n]", text or "")
    cleaned = []
    for part in parts:
        item = part.strip(" ，,、 ")
        if len(item) >= 8:
            cleaned.append(item)
    return cleaned


def extract_terms(text: str) -> list[str]:
    found: list[str] = []
    found += re.findall(r"[A-Za-z][A-Za-z0-9_\-+.]{1,}", text or "")
    found += re.findall(r"「([^」]{2,16})」", text or "")
    found += re.findall(r"\d+(?:\.\d+)?%?", text or "")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    if ordered:
        return ordered
    chunks = sentences(text)
    if chunks:
        return [chunks[0][:8]]
    fallback = (text or "").strip()[:8]
    return [fallback or "课题"]


def pick_snippet(text: str, salt: str) -> str:
    chunks = sentences(text)
    if not chunks:
        return (text or "").strip()[:34] or "这段摘要"
    choice = chunks[stable_index(salt, len(chunks))]
    return choice[:34]


def pick_term(text: str, salt: str) -> str:
    terms = extract_terms(text)
    return terms[stable_index(salt + ":term", len(terms))]


def make_title(text: str) -> str:
    chunks = sentences(text)
    raw = chunks[0] if chunks else (text or "").strip()
    raw = raw.strip()
    if not raw:
        return "未命名课题"
    if len(raw) > 22:
        return raw[:22] + "…"
    return raw


def clip_quote(answer: str, limit: int = 18) -> str:
    text = " ".join((answer or "").strip().split())
    text = text.replace("「", "“").replace("」", "”")
    return text[:limit]


def fill_template(template: str, mapping: dict[str, str]) -> str:
    """只替换模板自己的占位符，摘要里的花括号不会被当成格式串。"""
    pieces: list[str] = []
    index = 0
    while index < len(template):
        if template[index] == "{":
            end = template.find("}", index)
            if end != -1:
                key = template[index + 1 : end]
                if key in mapping:
                    pieces.append(str(mapping[key]))
                    index = end + 1
                    continue
        pieces.append(template[index])
        index += 1
    return "".join(pieces)


def normalize_abstract(text: str) -> str:
    cleaned = (text or "").replace("\x00", "").strip()
    if len(cleaned) < 20:
        raise ValueError("摘要至少写 20 个字，评委才知道从哪里下口。")
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000]
    return cleaned


def normalize_player(name: str | None) -> str:
    cleaned = " ".join((name or "").replace("\n", " ").split())
    cleaned = cleaned[:12]
    return cleaned or "同学"


def coerce_rounds(value) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = 6
    return max(4, min(8, number))


def parse_json_object(text: str) -> dict:
    """从模型输出里抠出一个 JSON 对象，容忍 Markdown 围栏和尾逗号。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型返回为空")
    fenced = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    fenced = re.sub(r"\s*```$", "", fenced).strip()
    candidates = [fenced, raw]
    start = fenced.find("{")
    end = fenced.rfind("}")
    if start >= 0 and end > start:
        candidates.append(fenced[start : end + 1])

    last_error: Exception | None = None
    seen: set[str] = set()
    for candidate in candidates:
        options = (candidate, re.sub(r",\s*([}\]])", r"\1", candidate))
        for attempt in options:
            if attempt in seen:
                continue
            seen.add(attempt)
            try:
                data = json.loads(attempt)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(data, dict):
                return data
    raise ValueError("模型没有返回可解析的 JSON") from last_error
