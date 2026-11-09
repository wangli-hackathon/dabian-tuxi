"""答辩状态机。模型只负责出题和口吻，伤害、破绽和旧账由这里收口。"""

from __future__ import annotations

import copy

from game.judges import JUDGE_ORDER, JUDGES
from game.llm import build_brain
from game.mock_brain import MockBrain
from game.scoring import (
    apply_scores,
    catalog_weakness,
    empty_scores,
    find_contradiction,
    normalize_verdict,
    share_text,
)
from game.textutil import (
    clip_quote,
    coerce_rounds,
    make_title,
    normalize_abstract,
    normalize_player,
    pick_snippet,
    pick_term,
)

__all__ = [
    "new_game",
    "submit_answer",
    "share_text",
    "choose_assignment",
    "select_memory",
]


def brain_for_mode(mode: str):
    if mode == "live":
        brain = build_brain()
        if getattr(brain, "mode", "mock") == "live":
            return brain
    return MockBrain()


def choose_assignment(state: dict) -> tuple[str, dict | None]:
    """前三轮每人先问一次。之后未补上的破绽优先，但同一评委最多连问两轮。"""
    cursor = state["cursor"]
    rotate = JUDGE_ORDER[cursor % 3]
    if cursor < 3:
        return rotate, None
    open_items = [
        item
        for item in state["weaknesses"]
        if not item["resolved"] and not item["exploited"]
    ]
    if not open_items:
        return rotate, None
    open_items.sort(key=lambda item: (-item["severity"], item["round"], item["id"]))
    top = open_items[0]
    if top["judge"] == state.get("last_judge") and state.get("judge_streak", 0) >= 2:
        return rotate, None
    return top["judge"], top


def select_memory(state: dict, judge_id: str, weakness: dict | None) -> dict | None:
    turns = state["turns"]
    if not turns:
        return None
    if weakness:
        for turn in turns:
            if weakness["id"] in turn.get("weaknesses_added", []):
                return turn
    if judge_id == "logic":
        return turns[0]
    return turns[-1]


def opening_lines(abstract: str) -> list[dict]:
    snippet = pick_snippet(abstract, "opening")
    term = pick_term(abstract, "opening")
    return [
        {
            "kind": "enter",
            "judge": "concept",
            "text": f"林知远把摘要摊平：「{snippet}」。今天先让概念自己站住。",
        },
        {
            "kind": "enter",
            "judge": "experiment",
            "text": f"周衡已经在页边写数字。他盯上了「{term}」，对照和样本少一个都别想混过去。",
        },
        {
            "kind": "enter",
            "judge": "logic",
            "text": "沈析翻开空白的追问页：你后面每句话，我都会跟前面的原话对一下。",
        },
    ]


def new_game(abstract: str, total_rounds: int = 6, player: str = "同学", brain=None) -> dict:
    text = normalize_abstract(abstract)
    if brain is None:
        brain = build_brain()
    settings = getattr(brain, "settings", None)
    state = {
        "abstract": text,
        "title": make_title(text),
        "player": normalize_player(player),
        "hp": 100,
        "max_hp": 100,
        "total_rounds": coerce_rounds(total_rounds),
        "cursor": 0,
        "status": "playing",
        "turns": [],
        "weaknesses": [],
        "scores": empty_scores(),
        "log": opening_lines(text),
        "pending": None,
        "last_judge": None,
        "judge_streak": 0,
        "mode": getattr(brain, "mode", "mock"),
        "model": getattr(settings, "model", "") if settings else "",
        "notice": "",
        "last_delta": 0,
    }
    _issue_question(state, brain)
    return state


def submit_answer(state: dict, answer: str, brain=None) -> dict:
    if not state or state.get("status") != "playing" or not state.get("pending"):
        return state
    state = copy.deepcopy(state)
    if brain is None:
        brain = brain_for_mode(state.get("mode", "mock"))
    text = (answer or "").strip()
    if not text:
        text = "（沉默）"
    text = text[:800]

    raw = brain.judge(state, text)
    judge_notice = getattr(brain, "last_notice", "") or ""
    verdict = normalize_verdict(raw)
    contradiction = str(raw.get("contradiction") or "").strip() or find_contradiction(state["turns"], text)
    if contradiction and verdict["quality"] in {"strong", "ok"}:
        verdict = _downgrade_for_contradiction(verdict)

    pending = state["pending"]
    round_no = pending["round"]
    judge_id = pending["judge"]
    hp = state["hp"] + verdict["hp_delta"]
    if hp > state["max_hp"]:
        hp = state["max_hp"]
    failed = hp <= 0
    state["hp"] = 0 if hp < 0 else hp
    state["last_delta"] = verdict["hp_delta"]
    state["scores"] = apply_scores(state["scores"], judge_id, verdict["quality_score"])

    added_ids, reinforced = _record_weakness(
        state, verdict, contradiction, judge_id, round_no, text
    )
    resolved_ids = _resolve_weaknesses(state, verdict, pending, added_ids)
    reaction = verdict["reaction"] or _fallback_reaction(judge_id, verdict["quality"])

    state["turns"].append(
        {
            "round": round_no,
            "judge": judge_id,
            "question": pending["question"],
            "answer": text,
            "reaction": reaction,
            "hp_delta": verdict["hp_delta"],
            "hp_after": state["hp"],
            "quality": verdict["quality"],
            "referenced_round": pending.get("referenced_round"),
            "referenced_quote": pending.get("referenced_quote") or "",
            "weaknesses_added": added_ids,
            "weaknesses_reinforced": reinforced,
            "weaknesses_resolved": resolved_ids,
            "targeted_weakness_id": pending.get("targets_weakness_id"),
            "source": raw.get("source") or pending.get("source") or "",
        }
    )
    state["cursor"] = round_no
    state["log"].append({"kind": "answer", "text": text, "round": round_no})
    state["log"].append(
        {
            "kind": "reaction",
            "judge": judge_id,
            "text": reaction,
            "round": round_no,
            "hp_delta": verdict["hp_delta"],
            "quality": verdict["quality"],
        }
    )

    if failed:
        state["status"] = "failed"
        state["pending"] = None
        state["notice"] = judge_notice
        state["log"].append(
            {
                "kind": "system",
                "text": "延毕警告：体力耗尽，委员会中止了这场答辩。",
                "round": round_no,
            }
        )
        return state
    if state["cursor"] >= state["total_rounds"]:
        state["status"] = "passed"
        state["pending"] = None
        state["notice"] = judge_notice
        state["log"].append(
            {
                "kind": "system",
                "text": "回合已尽。你还坐在席上，委员会准备宣读成绩。",
                "round": round_no,
            }
        )
        return state

    _issue_question(state, brain)
    ask_notice = state.get("notice") or ""
    parts = []
    for item in (judge_notice, ask_notice):
        if item and item not in parts:
            parts.append(item)
    state["notice"] = " ".join(parts)
    return state


def _downgrade_for_contradiction(verdict: dict) -> dict:
    updated = dict(verdict)
    updated["quality"] = "weak"
    updated["hp_delta"] = -16
    updated["quality_score"] = min(updated["quality_score"], 44)
    updated["resolved_weakness_ids"] = []
    return updated


def _fallback_reaction(judge_id: str, quality: str) -> str:
    name = JUDGES[judge_id]["name"]
    table = {
        "strong": f"{name}点了点头：这一问先过去。",
        "ok": f"{name}顿了顿：方向在，还没钉死。",
        "weak": f"{name}在纸边画了个圈：这里是破绽。",
        "collapse": f"{name}合上文件夹：再这样，延毕警告就不是玩笑了。",
    }
    return table.get(quality, table["ok"])


def _record_weakness(state, verdict, contradiction, judge_id, round_no, answer) -> tuple[list[str], list[str]]:
    need = verdict["quality"] in {"weak", "collapse"} or bool(contradiction)
    if not need:
        return [], []
    payload = _payload_from_verdict(verdict, judge_id, contradiction, round_no, answer, state)
    if payload is None:
        return [], []
    for item in state["weaknesses"]:
        if item["tag"] == payload["tag"] and not item["resolved"]:
            item["severity"] = min(3, item["severity"] + 1)
            item["detail"] = payload["detail"]
            return [], [item["id"]]
    weakness_id = f"w{len(state['weaknesses']) + 1}"
    state["weaknesses"].append(
        {
            "id": weakness_id,
            "tag": payload["tag"],
            "detail": payload["detail"],
            "round": round_no,
            "judge": judge_id,
            "severity": payload["severity"],
            "exploited": False,
            "resolved": False,
        }
    )
    return [weakness_id], []


def _payload_from_verdict(verdict, judge_id, contradiction, round_no, answer, state) -> dict | None:
    if contradiction:
        return {"tag": "前后说法不一致", "detail": contradiction[:40], "severity": 3}
    raw_list = verdict.get("new_weaknesses") or []
    if raw_list and isinstance(raw_list[0], dict):
        item = raw_list[0]
        tag = str(item.get("tag") or "").strip()[:12]
        detail = str(item.get("detail") or "").strip()[:80]
        if tag and detail:
            try:
                severity = int(item.get("severity") or 1)
            except (TypeError, ValueError):
                severity = 1
            return {"tag": tag, "detail": detail, "severity": max(1, min(3, severity))}
    if verdict["quality"] not in {"weak", "collapse"}:
        return None
    avoid = {item["tag"] for item in state["weaknesses"] if not item["resolved"]}
    severity = 2 if verdict["quality"] == "collapse" else 1
    return catalog_weakness(judge_id, answer, round_no, severity, avoid)


def _resolve_weaknesses(state, verdict, pending, added_ids) -> list[str]:
    if verdict["quality"] != "strong":
        return []
    candidates = list(verdict["resolved_weakness_ids"])
    target = pending.get("targets_weakness_id")
    if target:
        candidates.append(target)
    resolved = []
    blocked = set(added_ids)
    for weakness_id in candidates:
        if weakness_id in blocked or weakness_id in resolved:
            continue
        for item in state["weaknesses"]:
            if item["id"] == weakness_id and not item["resolved"]:
                item["resolved"] = True
                resolved.append(weakness_id)
                break
    return resolved


def _issue_question(state: dict, brain) -> None:
    judge_id, weakness = choose_assignment(state)
    memory = select_memory(state, judge_id, weakness)
    raw = brain.ask(state, judge_id, weakness, memory)
    question = str(raw.get("question") or "").strip()
    if len(question) < 8:
        question = MockBrain().ask(state, judge_id, weakness, memory)["question"]

    quote = ""
    referenced_round = None
    if memory:
        quote = clip_quote(memory["answer"])
        referenced_round = memory["round"]
        marker = f"「{quote}」"
        if quote and marker not in question and quote not in question:
            question = f"我还记得你第{referenced_round}轮说过「{quote}」。{question}"

    target_id = None
    if weakness:
        target_id = weakness["id"]
        if weakness["tag"] not in question:
            question = f"先回到破绽「{weakness['tag']}」：{weakness['detail']}{question}"
        for item in state["weaknesses"]:
            if item["id"] == target_id:
                item["exploited"] = True

    if len(question) > 500:
        question = question[:500]
    source = raw.get("source") or getattr(brain, "mode", "mock")
    state["pending"] = {
        "round": state["cursor"] + 1,
        "judge": judge_id,
        "question": question,
        "referenced_round": referenced_round,
        "referenced_quote": quote,
        "targets_weakness_id": target_id,
        "source": source,
    }
    if state.get("last_judge") == judge_id:
        state["judge_streak"] = state.get("judge_streak", 0) + 1
    else:
        state["judge_streak"] = 1
    state["last_judge"] = judge_id
    state["notice"] = getattr(brain, "last_notice", "") or ""
    state["log"].append(
        {
            "kind": "question",
            "judge": judge_id,
            "text": question,
            "round": state["pending"]["round"],
            "source": source,
        }
    )
