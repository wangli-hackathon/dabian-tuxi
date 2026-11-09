"""OpenAI 兼容客户端。默认走魔搭推理，失败时退回演示评委。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from game.judges import JUDGES
from game.mock_brain import MockBrain
from game.textutil import clip_quote, parse_json_object

DEFAULT_BASE_URL = "https://api-inference.modelscope.cn/v1/"
DEFAULT_MODEL = "Qwen/Qwen2.5-72B-Instruct"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/"
DASHSCOPE_MODEL = "qwen2.5-72b-instruct"
PLACEHOLDER_KEYS = {"", "mock", "offline", "none", "null"}

ASK_SYSTEM = """你是学位论文答辩游戏《答辩突袭》里的评委，不是通用助手。
只负责以指定人设提出一个追问。使用中文。问题要具体，对着摘要和已有回答下刀。
不要客套，不要一次抛出三个以上的问题，不要人身攻击。
如果用户消息要求引用原话，必须原样摘引，不要编造学生没说过的句子。
如果用户消息给了破绽，问题必须针对该破绽，并点出破绽名称。
只输出一个 JSON 对象，不要 Markdown。
格式：{"question":"...","memory_note":"十个字以内，没有则空字符串"}"""

JUDGE_SYSTEM = """你是学位论文答辩游戏《答辩突袭》里的评委，正在给刚刚这一答打分。
不要客气，但不要人身攻击，就事论事。使用中文。
quality 只能是 strong、ok、weak、collapse 之一。
hp_delta 必须与 quality 对应：strong=6，ok=-6，weak=-16，collapse=-26。
new_weaknesses 最多 1 条。每条含 tag（不超过 12 个字）、detail（不超过 40 个字）、severity（1 到 3 的整数）。
strong 通常不新增破绽。collapse 必须新增破绽。
resolved_weakness_ids 只能填写这一答确实补上的已有破绽 id。quality 为 collapse 时必须是空数组。
reaction 用该评委的口吻，40 到 80 字，点明理由。
quality_score 是 0 到 100 的整数。
只输出一个 JSON 对象，不要 Markdown。
格式：{"reaction":"...","quality":"ok","quality_score":68,"hp_delta":-6,"new_weaknesses":[],"resolved_weakness_ids":[]}"""


@dataclass(frozen=True)
class Settings:
    mode: str
    api_key: str
    base_url: str
    model: str
    key_source: str


def _clean_key(value: str | None) -> str:
    text = (value or "").strip()
    if text.lower() in PLACEHOLDER_KEYS:
        return ""
    return text


def _clean_base(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return DEFAULT_BASE_URL
    return text if text.endswith("/") else text + "/"


def _env_get(env, name: str) -> str:
    if env is None:
        return os.environ.get(name, "")
    return str(env.get(name, "") or "")


def resolve_settings(env=None) -> Settings:
    """决定在线还是演示，以及端点、模型。传入 dict 时不读进程环境。"""
    force_mock = _env_get(env, "DABIAN_MOCK").strip().lower() in {"1", "true", "yes", "on"}
    modelscope_key = _clean_key(_env_get(env, "MODELSCOPE_API_KEY"))
    dashscope_key = _clean_key(_env_get(env, "DASHSCOPE_API_KEY"))
    if modelscope_key:
        key, source = modelscope_key, "MODELSCOPE_API_KEY"
    elif dashscope_key:
        key, source = dashscope_key, "DASHSCOPE_API_KEY"
    else:
        key, source = "", ""

    override_base = _env_get(env, "MODELSCOPE_BASE_URL").strip()
    override_model = _env_get(env, "MODELSCOPE_MODEL").strip()
    dashscope_only = source == "DASHSCOPE_API_KEY" and not override_base
    if dashscope_only:
        base_url = DASHSCOPE_BASE_URL
    else:
        base_url = _clean_base(override_base or DEFAULT_BASE_URL)
    if override_model:
        model = override_model
    elif dashscope_only:
        model = DASHSCOPE_MODEL
    else:
        model = DEFAULT_MODEL

    mode = "mock" if force_mock or not key else "live"
    if mode == "mock":
        if not override_base:
            base_url = DEFAULT_BASE_URL
        if not override_model:
            model = DEFAULT_MODEL
        key, source = "", ""
    return Settings(mode=mode, api_key=key, base_url=base_url, model=model, key_source=source)


def build_brain(env=None):
    settings = resolve_settings(env)
    if settings.mode == "mock":
        return MockBrain()
    return LiveBrain(settings)


def _history_block(state: dict, limit: int = 6) -> str:
    turns = state.get("turns", [])[-limit:]
    if not turns:
        return "（还没有历史回答）"
    lines = []
    for turn in turns:
        role = JUDGES[turn["judge"]]["role"]
        lines.append(f"第{turn['round']}轮 {role}问：{turn['question'][:180]}")
        lines.append(f"第{turn['round']}轮 学生答：{turn['answer'][:220]}")
    return "\n".join(lines)


def _weakness_block(state: dict) -> str:
    rows = []
    for item in state.get("weaknesses", []):
        flag = "已补上" if item["resolved"] else "未补上"
        rows.append(
            f"- {item['id']} [{flag}] {item['tag']}（严重度 {item['severity']}）：{item['detail']}"
        )
    return "\n".join(rows) if rows else "（还没有破绽）"


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)


class LiveBrain:
    mode = "live"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_notice = ""
        self._mock = MockBrain()
        self.client = None

    def _client(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=40,
                max_retries=0,
            )
        return self.client

    def _complete(self, system: str, user: str, temperature: float) -> str:
        response = self._client().chat.completions.create(
            model=self.settings.model,
            temperature=temperature,
            max_tokens=800,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return _message_text(response.choices[0].message)

    def _complete_json(self, system: str, user: str, temperature: float) -> dict:
        prompt = user
        last_error: Exception | None = None
        for _ in range(2):
            try:
                content = self._complete(system, prompt, temperature)
                return parse_json_object(content)
            except Exception as exc:  # 网络、解析、空输出都再试一次
                last_error = exc
                prompt = user + "\n\n你上一次的输出无法解析。只输出一个 JSON 对象，不要 Markdown。"
        raise RuntimeError(type(last_error).__name__ if last_error else "LLMError")

    def ask(self, state: dict, judge_id: str, weakness: dict | None, memory: dict | None) -> dict:
        try:
            data = self._complete_json(ASK_SYSTEM, self._ask_prompt(state, judge_id, weakness, memory), 0.7)
            question = str(data.get("question") or "").strip()
            if len(question) < 8:
                raise ValueError("问题过短")
            self.last_notice = ""
            return {"question": question, "source": "live"}
        except Exception as exc:
            mocked = self._mock.ask(state, judge_id, weakness, memory)
            mocked["source"] = "fallback"
            self.last_notice = f"在线评委这回合没接上（{type(exc).__name__}），已改用演示题库，对局继续。"
            return mocked

    def judge(self, state: dict, answer: str) -> dict:
        try:
            data = self._complete_json(JUDGE_SYSTEM, self._judge_prompt(state, answer), 0.3)
            if not str(data.get("reaction") or "").strip():
                raise ValueError("缺少反应")
            data["source"] = "live"
            self.last_notice = ""
            return data
        except Exception as exc:
            mocked = self._mock.judge(state, answer)
            mocked["source"] = "fallback"
            self.last_notice = f"在线评委这回合没接上（{type(exc).__name__}），已改用演示题库，对局继续。"
            return mocked

    def _ask_prompt(self, state: dict, judge_id: str, weakness: dict | None, memory: dict | None) -> str:
        judge = JUDGES[judge_id]
        lines = [
            f"人设：{judge['name']}，{judge['role']}。口头禅：{judge['motto']}",
            f"回合：第 {state['cursor'] + 1} 轮，共 {state['total_rounds']} 轮。学生体力 {state['hp']}/100。",
            f"课题：{state['title']}",
            "摘要：",
            state["abstract"][:2000],
            "已有破绽：",
            _weakness_block(state),
            "历史问答：",
            _history_block(state),
        ]
        if memory:
            quote = clip_quote(memory["answer"])
            lines.append(
                f"必须在问题中原样引用第{memory['round']}轮学生原话：「{quote}」。不许改写这句原话。"
            )
        if weakness:
            lines.append(
                f"必须针对破绽 {weakness['id']}「{weakness['tag']}」来问：{weakness['detail']}"
            )
        lines.append("现在只输出 JSON。")
        return "\n".join(lines)

    def _judge_prompt(self, state: dict, answer: str) -> str:
        pending = state["pending"]
        judge = JUDGES[pending["judge"]]
        lines = [
            f"人设：{judge['name']}，{judge['role']}。",
            f"课题：{state['title']}",
            "摘要：",
            state["abstract"][:2000],
            f"本轮问题：{pending['question']}",
            f"学生这一答：{answer[:800]}",
            "已有破绽：",
            _weakness_block(state),
            "历史问答：",
            _history_block(state),
            "按系统要求只输出 JSON。",
        ]
        return "\n".join(lines)
