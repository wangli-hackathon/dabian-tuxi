"""把对局渲染成答辩席。用户原文一律转义。"""

from __future__ import annotations

import html

from game.judges import JUDGE_ORDER, JUDGES, avatar_src
from game.scoring import build_report, pressure_of, share_text

SOURCE_LABEL = {"mock": "演示", "live": "在线", "fallback": "题库顶上"}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def judge_card(judge_id: str, active: bool) -> str:
    judge = JUDGES[judge_id]
    css = "judge active" if active else "judge"
    return (
        f'<article class="{css}" data-judge="{judge_id}">'
        f'<img class="seal" alt="" src="{avatar_src(judge_id)}" />'
        '<div class="judge-copy">'
        f'<strong>{judge["emoji"]} {_esc(judge["name"])}</strong>'
        f'<em>{_esc(judge["role"])}</em>'
        f'<p>{_esc(judge["motto"])}</p>'
        "</div></article>"
    )


def render_lobby(mode_label: str) -> str:
    cards = "".join(judge_card(judge_id, False) for judge_id in JUDGE_ORDER)
    return f"""
    <section class="hero">
      <div class="hero-top">
        <div class="brand-seal" aria-hidden="true">答</div>
        <div>
          <p class="kicker">魔搭 AI+∞ · AI 造游戏</p>
          <h1>答辩突袭</h1>
          <p class="pitch">把课程小结或开题摘要交上去。三位评委带着记忆轮流追问，旧回答会被当场摘出来。体力归零，就是延毕警告。</p>
        </div>
      </div>
      <ol class="steps">
        <li><span>1</span>交上摘要</li>
        <li><span>2</span>逐回合作答</li>
        <li><span>3</span>撑完拿成绩单</li>
      </ol>
      <div class="judge-row">{cards}</div>
      <p class="mode-line">{_esc(mode_label)}</p>
    </section>
    """


def render_stage(state: dict | None) -> str:
    if not state:
        return ""
    active = (state.get("pending") or {}).get("judge")
    cards = "".join(judge_card(judge_id, judge_id == active) for judge_id in JUDGE_ORDER)
    shake = " shake" if state.get("last_delta", 0) <= -16 else ""
    ended = state.get("status") in {"passed", "failed"}
    flash = " is-fail" if state.get("status") == "failed" else ""
    flash += " is-pass" if state.get("status") == "passed" else ""
    return f"""
    <section class="arena{shake}{flash}" data-testid="arena">
      {_topbar(state)}
      <div class="topic-strip"><span>课题</span><strong>{_esc(state["title"])}</strong></div>
      <div class="judge-row">{cards}</div>
      {_meters(state)}
      {_weaknesses(state)}
      {_notice(state)}
      {_spotlight(state) if not ended else _report(state)}
      {_history(state)}
    </section>
    """


def _topbar(state: dict) -> str:
    mode = "在线模式" if state.get("mode") == "live" else "演示模式"
    if state.get("status") == "playing":
        progress = f"第 {state['pending']['round']} 轮 · 共 {state['total_rounds']} 轮"
    elif state.get("status") == "passed":
        progress = f"已完成 {state['cursor']}/{state['total_rounds']} 轮"
    else:
        progress = f"停在第 {state['cursor']} 轮"
    return f"""
    <header class="topbar">
      <div class="brand-mini"><b>答辩突袭</b><small>{_esc(state.get("player") or "同学")}</small></div>
      <div class="round-pill" data-testid="round-label">{_esc(progress)}</div>
      <div class="mode-pill" data-testid="mode-pill">{mode}</div>
    </header>
    """


def _meters(state: dict) -> str:
    hp = int(state["hp"])
    stress = pressure_of(state)
    patience = ""
    if state.get("status") == "playing":
        patience = """
        <div class="meter">
          <div class="meter-label"><span>评委耐心</span><span>约 90 秒</span></div>
          <div class="track"><div class="fill sand"></div></div>
        </div>
        """
    return f"""
    <div class="meter-row">
      <div class="meter">
        <div class="meter-label"><span>答辩体力</span><span data-testid="hp-value">{hp}</span></div>
        <div class="track"><div class="fill hp" style="width:{hp}%"></div></div>
      </div>
      <div class="meter">
        <div class="meter-label"><span>压力</span><span data-testid="stress-value">{stress}</span></div>
        <div class="track"><div class="fill stress" style="width:{stress}%"></div></div>
      </div>
      {patience}
    </div>
    """


def _weaknesses(state: dict) -> str:
    items = state.get("weaknesses") or []
    pending = state.get("pending") or {}
    if not items:
        body = '<p class="empty-weak">破绽栏还空着。别高兴太早。</p>'
    else:
        chips = []
        for item in items:
            if item["resolved"]:
                css, label = "resolved", "已补上"
            elif pending.get("targets_weakness_id") == item["id"]:
                css, label = "hot", "正在追问"
            elif item["exploited"]:
                css, label = "used", "已追问"
            else:
                css, label = "open", "未追问"
            chips.append(
                f'<span class="chip {css}" data-testid="weakness">'
                f'{_esc(item["tag"])}<em>{label}</em></span>'
            )
        body = "".join(chips)
    return f'<div class="weak-row"><span class="weak-k">破绽</span>{body}</div>'


def _notice(state: dict) -> str:
    text = (state.get("notice") or "").strip()
    if not text:
        return ""
    return f'<p class="notice" data-testid="notice">{_esc(text)}</p>'


def _spotlight(state: dict) -> str:
    pending = state["pending"]
    judge = JUDGES[pending["judge"]]
    source = SOURCE_LABEL.get(pending.get("source") or "", "演示")
    memory = ""
    if pending.get("referenced_quote"):
        memory = (
            f'<p class="memory">翻旧账 · 第 {pending["referenced_round"]} 轮'
            f'「{_esc(pending["referenced_quote"])}」</p>'
        )
    target = ""
    target_id = pending.get("targets_weakness_id")
    if target_id:
        match = next((item for item in state["weaknesses"] if item["id"] == target_id), None)
        if match:
            target = f'<p class="target">正在追这条破绽 · {_esc(match["tag"])}</p>'
    return f"""
    <article class="now-card" data-testid="question">
      <p class="now-kicker">第 {pending["round"]} 轮 · {judge["emoji"]} {_esc(judge["name"])} · {_esc(judge["role"])}
        <em>{source}</em></p>
      {memory}
      {target}
      <p class="now-q">{_esc(pending["question"])}</p>
    </article>
    """


def _history(state: dict) -> str:
    entries = list(state.get("log") or [])
    if state.get("status") == "playing" and entries and entries[-1].get("kind") == "question":
        entries = entries[:-1]
    hidden = max(0, len(entries) - 8)
    entries = entries[-8:]
    if not entries:
        return ""
    bubbles = []
    if hidden:
        bubbles.append(f'<p class="folded">更早的 {hidden} 条已经折进评委记忆。</p>')
    for entry in entries:
        bubbles.append(_bubble(entry))
    return f'<div class="log">{"".join(bubbles)}</div>'


def _bubble(entry: dict) -> str:
    kind = entry.get("kind")
    if kind == "answer":
        return (
            '<div class="bubble player"><span>你 · '
            f'第 {entry["round"]} 轮</span><p>{_esc(entry["text"])}</p></div>'
        )
    if kind == "system":
        return f'<div class="bubble system"><p>{_esc(entry["text"])}</p></div>'
    if kind == "reaction":
        judge = JUDGES[entry["judge"]]
        delta = int(entry.get("hp_delta") or 0)
        if delta > 0:
            delta_text, css = f"体力 +{delta}", "up"
        elif delta < 0:
            delta_text, css = f"体力 {delta}", "down"
        else:
            delta_text, css = "体力不变", "flat"
        return (
            f'<div class="bubble judge-line {entry["judge"]}">'
            f'<span>{judge["emoji"]} {_esc(judge["name"])} · 第 {entry["round"]} 轮'
            f'<b class="{css}">{delta_text}</b></span>'
            f'<p>{_esc(entry["text"])}</p></div>'
        )
    if kind == "enter":
        judge = JUDGES[entry["judge"]]
        return (
            f'<div class="bubble enter {entry["judge"]}">'
            f'<span>{judge["emoji"]} {_esc(judge["role"])}入场</span>'
            f'<p>{_esc(entry["text"])}</p></div>'
        )
    judge = JUDGES.get(entry.get("judge") or "", {})
    who = f'{judge.get("emoji", "")} {_esc(judge.get("name", "评委"))}'
    return f'<div class="bubble question"><span>{who}</span><p>{_esc(entry.get("text", ""))}</p></div>'


def _report(state: dict) -> str:
    report = build_report(state)
    passed = state.get("status") == "passed"
    stamp = "答辩通过" if passed else "延毕警告"
    css = "pass" if passed else "fail"
    confetti = ""
    if passed:
        confetti = '<div class="confetti" aria-hidden="true"><i>🎓</i><i>📜</i><i>✨</i><i>🍵</i><i>⭐</i></div>'
    dims = []
    for key, label in (("concept", "概念"), ("experiment", "实验"), ("logic", "逻辑")):
        value = report[key]
        dims.append(
            f'<div class="dim"><span>{label}</span><b>{value}</b>'
            f'<div class="track"><div class="fill dimfill" style="width:{value}%"></div></div></div>'
        )
    quotes = []
    for item in report["highlights"]:
        judge = JUDGES[item["judge"]]
        quotes.append(
            f'<li><b>{judge["emoji"]} {_esc(judge["name"])}</b>{_esc(item["text"])}</li>'
        )
    quote_html = "".join(quotes) or "<li>评委还没留下原话。</li>"
    shared = share_text(state)
    return f"""
    <article class="report" data-testid="report">
      {confetti}
      <div class="stamp {css}" data-testid="outcome">{stamp}</div>
      <p class="grade">成绩 {_esc(report["grade"])} · 综合 {report["overall"]}</p>
      <p class="comment">{_esc(report["comment"])}</p>
      <div class="dim-row">{"".join(dims)}</div>
      <ul class="quotes">{quote_html}</ul>
      <p class="memory-line">{_esc(report["memory_line"])}</p>
      <pre class="share-preview" data-testid="share-preview">{_esc(shared)}</pre>
    </article>
    """
