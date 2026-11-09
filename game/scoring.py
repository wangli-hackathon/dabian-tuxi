"""打分、破绽目录、伤害钳制和成绩单。在线和演示模式共用同一套钳制。"""

from __future__ import annotations

import re

from game.judges import JUDGES
from game.textutil import as_int, clamp, stable_index

DIMENSIONS = ("concept", "experiment", "logic")

BUNDLES = {
    "concept": ["定义", "是指", "区别", "边界", "概念", "框架", "操作", "内涵", "外延", "正例", "反例"],
    "experiment": ["对照", "样本", "基线", "实验", "指标", "数据", "随机", "复现", "消融", "显著", "分组"],
    "logic": ["因为", "所以", "因此", "如果", "假设", "然而", "尽管", "因果", "推出", "前提", "相关"],
}

DODGE_WORDS = ["不知道", "没想好", "随便", "不清楚", "忘了", "无语", "哈哈哈"]

# 这两端不能互为子串，否则「不显著」会误伤「显著」。
CONTRADICTION_PAIRS = [
    ("正相关", "负相关"),
    ("提升明显", "完全没效果"),
    ("随机分组", "便利抽样"),
]

QUALITY_DELTA = {"strong": 6, "ok": -6, "weak": -16, "collapse": -26}
QUALITY_SCORE = {"strong": 86, "ok": 68, "weak": 50, "collapse": 18}
DELTA_BANDS = {
    "strong": (0, 8),
    "ok": (-10, -2),
    "weak": (-22, -12),
    "collapse": (-28, -20),
}

WEAKNESS_CATALOG = {
    "concept": [
        ("概念边界模糊", "核心概念和邻近概念缠在一起，听不出边界。"),
        ("定义不可操作", "定义停在形容词上，没有说怎么核对。"),
    ],
    "experiment": [
        ("缺少对照", "结论已经出口，对照和基线还没出现。"),
        ("样本交代不清", "谁被测、测了多少，回答里没站住。"),
    ],
    "logic": [
        ("因果表述过满", "相关的结果被说成了因果。"),
        ("结论跳步", "从证据到结论中间缺了一截推导。"),
    ],
}

LOW_NAME = {"concept": "概念界定", "experiment": "实验设计", "logic": "逻辑链"}


def empty_scores() -> dict[str, int]:
    return {"concept": 70, "experiment": 70, "logic": 70}


def score_answer(answer: str, judge_id: str, question: str) -> int:
    text = (answer or "").strip()
    if text in {"（沉默）", "沉默"}:
        return 8
    score = 46
    length = len(text)
    if length < 6:
        score -= 34
    elif length < 14:
        score -= 18
    elif length < 28:
        score -= 6
    elif length <= 220:
        score += 10
    else:
        score += 4
    hits = sum(1 for word in BUNDLES[judge_id] if word in text)
    score += min(hits, 4) * 7
    for other, words in BUNDLES.items():
        if other == judge_id:
            continue
        crossed = sum(1 for word in words if word in text)
        score += min(crossed, 3) * 2
    if any(word in text for word in ["例如", "比如", "举例", "具体来说"]):
        score += 6
    if re.search(r"\d", text):
        score += 4
    if any(word in text for word in DODGE_WORDS):
        score -= 30
    if length >= 12 and text in (question or ""):
        score = min(score, 36)
    return clamp(score, 0, 100)


def quality_from_score(score: int) -> tuple[str, int]:
    if score >= 78:
        return "strong", QUALITY_DELTA["strong"]
    if score >= 62:
        return "ok", QUALITY_DELTA["ok"]
    if score >= 45:
        return "weak", QUALITY_DELTA["weak"]
    return "collapse", QUALITY_DELTA["collapse"]


def find_contradiction(turns: list[dict], answer: str) -> str:
    previous = "\n".join(turn.get("answer", "") for turn in turns)
    current = answer or ""
    for left, right in CONTRADICTION_PAIRS:
        if left in previous and right in current and left not in current:
            return f"前面说过「{left}」，这一轮又改口「{right}」"
        if right in previous and left in current and right not in current:
            return f"前面说过「{right}」，这一轮又改口「{left}」"
    return ""


def catalog_weakness(judge_id: str, answer: str, round_no: int, severity: int, avoid: set[str]) -> dict:
    bank = WEAKNESS_CATALOG[judge_id]
    start = stable_index(f"{answer}|{round_no}|{judge_id}", len(bank))
    chosen = bank[start]
    for offset in range(len(bank)):
        tag, detail = bank[(start + offset) % len(bank)]
        if tag not in avoid:
            chosen = (tag, detail)
            break
    tag, detail = chosen
    return {"tag": tag, "detail": detail, "severity": clamp(severity, 1, 3)}


def apply_scores(scores: dict[str, int], judge_id: str, quality_score: int) -> dict[str, int]:
    updated = dict(scores)
    delta = clamp(round((quality_score - 60) / 5), -12, 10)
    for key in DIMENSIONS:
        weight = 1.0 if key == judge_id else 0.4
        updated[key] = clamp(round(updated[key] + delta * weight), 0, 100)
    return updated


def normalize_verdict(raw: dict | None) -> dict:
    """把模型的自由发挥收束到游戏能承受的伤害和档位。"""
    data = raw if isinstance(raw, dict) else {}
    quality = str(data.get("quality") or "ok").strip().lower()
    if quality not in QUALITY_DELTA:
        quality = "ok"
    expected = QUALITY_DELTA[quality]
    delta = as_int(data.get("hp_delta"), expected)
    low, high = DELTA_BANDS[quality]
    if delta < low or delta > high:
        delta = expected
    delta = clamp(delta, -28, 8)
    quality_score = clamp(as_int(data.get("quality_score"), QUALITY_SCORE[quality]), 0, 100)
    reaction = str(data.get("reaction") or "").strip()[:200]
    weaknesses = data.get("new_weaknesses") or []
    if not isinstance(weaknesses, list):
        weaknesses = []
    resolved = data.get("resolved_weakness_ids") or []
    if not isinstance(resolved, list):
        resolved = []
    resolved_ids = [str(item) for item in resolved if item][:3]
    if quality == "collapse":
        resolved_ids = []
    return {
        "quality": quality,
        "hp_delta": delta,
        "quality_score": quality_score,
        "reaction": reaction,
        "new_weaknesses": weaknesses[:1],
        "resolved_weakness_ids": resolved_ids,
    }


def pressure_of(state: dict) -> int:
    return clamp(100 - int(state.get("hp", 0)), 0, 100)


def _memory_line(state: dict) -> str:
    quoted = [turn for turn in state.get("turns", []) if turn.get("referenced_quote")]
    if not quoted:
        return "评委还没来得及翻旧账。"
    last = quoted[-1]
    name = JUDGES[last["judge"]]["name"]
    return (
        f"{name}在第{last['round']}轮摘了第{last['referenced_round']}轮的原话"
        f"「{last['referenced_quote']}」。"
    )


def _comment(status: str, lowest: str, weakness_count: int, resolved: int) -> str:
    part = LOW_NAME[lowest]
    if status == "failed":
        text = f"委员会中止了答辩，并给出延毕警告。场上最塌的是{part}。"
    elif status == "passed":
        text = f"你撑完了规定回合。委员会同意通过，但{part}仍是修改意见的第一行。"
    else:
        text = "答辩还没结束。"
    if weakness_count:
        text += f"破绽共 {weakness_count} 条，补上 {resolved} 条。"
    else:
        text += "破绽栏是空的，这很少见。"
    return text


def build_report(state: dict) -> dict:
    scores = state["scores"]
    hp = int(state["hp"])
    overall = round(
        0.30 * scores["concept"]
        + 0.30 * scores["experiment"]
        + 0.25 * scores["logic"]
        + 0.15 * max(hp, 0)
    )
    status = state.get("status")
    if status == "failed":
        outcome, grade = "延毕警告", "不及格"
    elif status == "passed":
        outcome = "答辩通过"
        if overall >= 85:
            grade = "优秀"
        elif overall >= 72:
            grade = "良好"
        elif overall >= 60:
            grade = "及格"
        else:
            grade = "险过"
    else:
        outcome, grade = "答辩进行中", "未出分"
    weaknesses = state.get("weaknesses", [])
    exploited = sum(1 for item in weaknesses if item.get("exploited"))
    resolved = sum(1 for item in weaknesses if item.get("resolved"))
    lowest = min(DIMENSIONS, key=lambda key: (scores[key], key))
    highlights = []
    seen: set[str] = set()
    for turn in reversed(state.get("turns", [])):
        judge_id = turn["judge"]
        if judge_id in seen:
            continue
        seen.add(judge_id)
        highlights.append({"judge": judge_id, "text": turn["reaction"], "round": turn["round"]})
        if len(seen) == 3:
            break
    highlights.reverse()
    return {
        "outcome": outcome,
        "grade": grade,
        "overall": overall,
        "concept": scores["concept"],
        "experiment": scores["experiment"],
        "logic": scores["logic"],
        "hp": hp,
        "pressure": pressure_of(state),
        "weakness_count": len(weaknesses),
        "exploited_count": exploited,
        "resolved_count": resolved,
        "comment": _comment(status, lowest, len(weaknesses), resolved),
        "memory_line": _memory_line(state),
        "highlights": highlights,
        "lowest": lowest,
    }


def share_text(state: dict) -> str:
    if state.get("status") not in {"passed", "failed"}:
        return ""
    report = build_report(state)
    lines = [
        "《答辩突袭》成绩单",
        f"答辩人：{state.get('player') or '同学'}",
        f"课题：{state.get('title') or '未命名课题'}",
        f"结局：{report['outcome']} · {report['grade']}",
        f"综合：{report['overall']}",
        f"体力：{state['hp']}/100 · 压力：{report['pressure']}",
        f"回合：{state['cursor']}/{state['total_rounds']}",
        f"概念 {report['concept']} · 实验 {report['experiment']} · 逻辑 {report['logic']}",
        (
            f"破绽 {report['weakness_count']} 处，追问 {report['exploited_count']} 次，"
            f"补上 {report['resolved_count']} 处"
        ),
        f"评委备忘：{report['memory_line']}",
        report["comment"],
    ]
    return "\n".join(lines)
