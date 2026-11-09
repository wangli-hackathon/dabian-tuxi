"""无密钥时的确定性评委。同一摘要、同一回答，题目和扣血逐字相同。"""

from __future__ import annotations

from game.judges import JUDGES
from game.scoring import (
    catalog_weakness,
    find_contradiction,
    quality_from_score,
    score_answer,
)
from game.textutil import fill_template, pick_snippet, pick_term, stable_index

TEMPLATES = {
    "concept": [
        "摘要里这句我画了线：「{snippet}」。请给核心概念一个操作化定义，并划出它和最容易混淆的概念之间的边界。",
        "先把「{term}」从口号里救出来。内涵是什么，外延到哪里为止？请给一个正例和一个反例。",
        "如果只能用一句不靠术语堆叠的人话重述「{title}」，你怎么说？这个概念靠的是哪一个框架？",
    ],
    "experiment": [
        "我只听得进设计。「{snippet}」——对照是谁，样本有多少，基线用什么指标？形容词不要算数。",
        "假设今晚我就要复现「{term}」。数据从哪来，指标怎么计算，做不做消融？缺的部分直接说缺。",
        "最小可行实验怎么做？随机分组还是方便样本？你打算用哪一个数字证明这不是巧合？",
    ],
    "logic": [
        "把逻辑链摊开。「{snippet}」从哪一个前提推到你的结论？按前提、证据、推论的顺序说，不要跳。",
        "「{term}」如果只是相关，你的措辞哪里说过了头？请改成你真的能担保的那一句。",
        "假设最关键的前提不成立，结论还剩下什么？指出最弱的一环，不要把摘要再读一遍。",
    ],
}

WEAK_TEMPLATES = {
    "concept": [
        "破绽还挂在黑板上：「{tag}」。{detail}这一轮只补这里。",
        "我不换题。「{tag}」——{detail}请给一个别人能核对的补法。",
    ],
    "experiment": [
        "实验账还没平。「{tag}」。{detail}只回答这一处。",
        "别换课题。「{tag}」还在：{detail}用对照、样本、指标把它补上。",
    ],
    "logic": [
        "逻辑这里断过。「{tag}」。{detail}把跳过的那一步补出来。",
        "我还盯着「{tag}」。{detail}这一轮不要展开新结论。",
    ],
}

REACTIONS = {
    "concept": {
        "strong": [
            "定义和边界这次都摸到了。概念这一关，我先放你过。",
            "可以。你没有拿术语去解释术语。",
        ],
        "ok": [
            "方向对，但边界还是软的。我先记一笔，不按破绽算。",
            "听懂了大概，离可检查还差半步。",
        ],
        "weak": [
            "这还停在形容词上。",
            "概念没有落地。",
        ],
        "collapse": [
            "这一答我没法往下接。",
            "你在躲定义。",
        ],
    },
    "experiment": {
        "strong": [
            "对照、样本、指标都开口了。实验这一问，算你站住了。",
            "这才像能复现的说法。我先不追。",
        ],
        "ok": [
            "有设计的影子，但数字还不够狠。先记下，不算致命。",
            "基线没说死。这次放你一马，下回我要数字。",
        ],
        "weak": [
            "没有对照的结论，我只当感想。",
            "样本和指标至少缺了一块。",
        ],
        "collapse": [
            "这不是实验，这是愿望。",
            "复现不了的话，委员会不会点头。",
        ],
    },
    "logic": {
        "strong": [
            "前提、证据、推论对齐了。这句我挑不出刺。",
            "你把相关和因果分开了。逻辑上，这一问过。",
        ],
        "ok": [
            "链条在，中间还有一点滑。我先不记破绽。",
            "能听懂你的推论，但还没钉死。",
        ],
        "weak": [
            "这里跳步了。",
            "结论比证据跑得快。",
        ],
        "collapse": [
            "前后对不上，还要我帮你圆？",
            "逻辑断了。",
        ],
    },
}


class MockBrain:
    mode = "mock"
    settings = None

    def __init__(self) -> None:
        self.last_notice = ""

    def ask(self, state: dict, judge_id: str, weakness: dict | None, memory: dict | None) -> dict:
        del memory  # 摘引由引擎强制贴上，避免模板和引擎各引一次。
        abstract = state["abstract"]
        round_no = state["cursor"] + 1
        bank = WEAK_TEMPLATES[judge_id] if weakness else TEMPLATES[judge_id]
        salt = f"{abstract}|{round_no}|{judge_id}|{(weakness or {}).get('id', '')}"
        template = bank[stable_index(salt, len(bank))]
        question = fill_template(
            template,
            {
                "snippet": pick_snippet(abstract, f"{judge_id}:{round_no}:{state['title']}"),
                "term": pick_term(abstract, f"{judge_id}:{round_no}"),
                "title": state["title"],
                "tag": (weakness or {}).get("tag", ""),
                "detail": (weakness or {}).get("detail", ""),
            },
        )
        self.last_notice = ""
        return {"question": question, "source": "mock"}

    def judge(self, state: dict, answer: str) -> dict:
        pending = state["pending"]
        judge_id = pending["judge"]
        score = score_answer(answer, judge_id, pending["question"])
        contradiction = find_contradiction(state["turns"], answer)
        if answer.strip() in {"（沉默）", "沉默"}:
            score = min(score, 8)
        if contradiction:
            score = max(0, score - 18)
        quality, delta = quality_from_score(score)
        open_tags = {item["tag"] for item in state["weaknesses"] if not item["resolved"]}
        payload = None
        if contradiction:
            payload = {
                "tag": "前后说法不一致",
                "detail": contradiction[:40],
                "severity": 3,
            }
        elif quality in {"weak", "collapse"}:
            severity = 2 if quality == "collapse" else 1
            payload = catalog_weakness(judge_id, answer, pending["round"], severity, open_tags)
        resolved: list[str] = []
        if quality == "strong" and pending.get("targets_weakness_id"):
            resolved = [pending["targets_weakness_id"]]
        tag = payload["tag"] if payload else ""
        self.last_notice = ""
        return {
            "reaction": self._reaction(judge_id, quality, tag, contradiction, answer),
            "quality": quality,
            "quality_score": score,
            "hp_delta": delta,
            "new_weaknesses": [payload] if payload else [],
            "resolved_weakness_ids": resolved,
            "contradiction": contradiction,
            "source": "mock",
        }

    def _reaction(self, judge_id: str, quality: str, tag: str, contradiction: str, answer: str) -> str:
        if contradiction:
            name = JUDGES[judge_id]["name"]
            return f"{name}把笔放下：别急着圆。{contradiction}。这一条记成「前后说法不一致」。"
        options = REACTIONS[judge_id][quality]
        text = options[stable_index(answer + quality + judge_id, len(options))]
        if tag and quality in {"weak", "collapse"}:
            text += f"破绽记为「{tag}」。"
        return text
