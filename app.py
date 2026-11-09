"""答辩突袭 · 魔搭创空间入口。

本地：python app.py
无密钥时自动进入演示模式，对局仍然完整。
"""

from __future__ import annotations

import os

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from pathlib import Path

import gradio as gr

from game.engine import new_game, submit_answer
from game.llm import resolve_settings
from game.render import render_lobby, render_stage
from game.samples import SAMPLES
from game.scoring import share_text

CSS = Path(__file__).resolve().parent.joinpath("game", "theme.css").read_text(encoding="utf-8")
CUSTOM = "自己粘贴"
SAMPLE_LABELS = [label for label, _ in SAMPLES]
SAMPLE_TEXT = {label: text for label, text in SAMPLES}
SCAFFOLDS = {
    "先下定义": "我先给操作化定义：",
    "补实验": "实验上我补这三块：对照、样本、指标。",
    "补逻辑": "逻辑链按前提、证据、推论来说：因为",
}


def mode_label() -> str:
    settings = resolve_settings()
    if settings.mode == "mock":
        return "演示模式 · 没检测到密钥。题库主持本局，同一份摘要和回答会得到同一场答辩。配上 MODELSCOPE_API_KEY 后改由 Qwen 出题。"
    return f"在线模式 · {settings.model}"


def load_sample(choice: str):
    if choice in SAMPLE_TEXT:
        return SAMPLE_TEXT[choice]
    return gr.update()


def _append_scaffold(current: str, prefix: str) -> str:
    current = current or ""
    if prefix in current:
        return current
    if current and not current.endswith("\n"):
        current += "\n"
    return current + prefix


def use_define(text: str) -> str:
    return _append_scaffold(text, SCAFFOLDS["先下定义"])


def use_experiment(text: str) -> str:
    return _append_scaffold(text, SCAFFOLDS["补实验"])


def use_logic(text: str) -> str:
    return _append_scaffold(text, SCAFFOLDS["补逻辑"])


def _pack(state, message: str = "", clear_answer: bool = False):
    playing = bool(state) and state.get("status") == "playing"
    ended = bool(state) and state.get("status") in {"passed", "failed"}
    answer_update = gr.update(visible=playing)
    if clear_answer:
        answer_update = gr.update(value="", visible=playing)
    return (
        state,
        gr.update(visible=not state),
        gr.update(visible=bool(state)),
        render_stage(state) if state else "",
        answer_update,
        gr.update(visible=playing),
        gr.update(visible=playing),
        gr.update(value=share_text(state) if ended else "", visible=ended),
        message,
    )


def start_game(abstract: str, rounds: float, player: str):
    try:
        state = new_game(abstract, total_rounds=rounds, player=player)
    except ValueError as exc:
        return _pack(None, str(exc))
    return _pack(state, clear_answer=True)


def answer_round(answer: str, state):
    if not state or state.get("status") != "playing":
        return _pack(state, "这一局还没开始，或已经结束。")
    updated = submit_answer(state, answer)
    return _pack(updated, clear_answer=True)


def back_to_lobby():
    return _pack(None, "")


def build_demo() -> gr.Blocks:
    theme = gr.themes.Base(
        primary_hue=gr.themes.colors.red,
        secondary_hue=gr.themes.colors.stone,
        neutral_hue=gr.themes.colors.stone,
        font=["Noto Sans SC", "WenQuanYi Micro Hei", "Droid Sans Fallback", "sans-serif"],
    ).set(
        body_background_fill="#12100e",
        body_background_fill_dark="#12100e",
        body_text_color="#f6f0e4",
        body_text_color_dark="#f6f0e4",
        block_background_fill="#1c1814",
        block_background_fill_dark="#1c1814",
        block_border_color="rgba(198,161,91,0.35)",
        block_border_color_dark="rgba(198,161,91,0.35)",
        block_label_text_color="#f6f0e4",
        block_label_text_color_dark="#f6f0e4",
        input_background_fill="#f6f0e4",
        input_background_fill_dark="#f6f0e4",
        input_border_color="#ddcfb8",
        input_border_color_dark="#ddcfb8",
        button_primary_background_fill="#8d2b2b",
        button_primary_background_fill_dark="#8d2b2b",
        button_primary_background_fill_hover="#a33b32",
        button_primary_background_fill_hover_dark="#a33b32",
        button_primary_text_color="#fff8ee",
        button_primary_text_color_dark="#fff8ee",
        button_secondary_background_fill="#1c1814",
        button_secondary_background_fill_dark="#1c1814",
        button_secondary_text_color="#f6f0e4",
        button_secondary_text_color_dark="#f6f0e4",
        button_secondary_border_color="rgba(198,161,91,0.45)",
        button_secondary_border_color_dark="rgba(198,161,91,0.45)",
    )
    with gr.Blocks(css=CSS, title="答辩突袭", theme=theme) as demo:
        state = gr.State(None)
        with gr.Column(elem_id="defense-app"):
            with gr.Column(visible=True) as setup_col:
                gr.HTML(render_lobby(mode_label()))
                with gr.Column(elem_classes=["sheet"]):
                    sample = gr.Radio(
                        choices=[CUSTOM, *SAMPLE_LABELS],
                        value=SAMPLE_LABELS[0],
                        label="快速入场",
                    )
                    player = gr.Textbox(label="答辩人怎么称呼", value="同学", max_lines=1)
                    abstract = gr.Textbox(
                        label="课程小结或开题摘要",
                        lines=8,
                        value=SAMPLE_TEXT[SAMPLE_LABELS[0]],
                        placeholder="粘贴课程小结或开题摘要。评委会按原文追问，不要只丢一个题目。",
                        elem_id="abstract-box",
                    )
                    rounds = gr.Slider(minimum=4, maximum=8, value=6, step=1, label="回合数")
                    with gr.Accordion("这局怎么判", open=False):
                        gr.Markdown(
                            "前三轮三位评委各问一次。之后没补上的破绽会被原主追问，"
                            "同一人最多连问两轮。答得好最多回 6 点体力，答砸了掉血并留下破绽。"
                            "体力归零是延毕警告；撑完回合才有成绩单。耐心条只是气氛，不强制交卷。"
                        )
                    start = gr.Button("坐上答辩席", variant="primary", elem_classes=["action-btn"])
                    setup_msg = gr.Markdown("")

            with gr.Column(visible=False) as play_col:
                battle = gr.HTML()
                answer = gr.Textbox(
                    label="你的回答",
                    lines=4,
                    placeholder="写完整句。评委会摘引你的原话，空话会被记成破绽。",
                )
                with gr.Row() as scaffolds:
                    define_btn = gr.Button("先下定义", elem_classes=["ghost-btn"])
                    experiment_btn = gr.Button("补实验", elem_classes=["ghost-btn"])
                    logic_btn = gr.Button("补逻辑", elem_classes=["ghost-btn"])
                with gr.Row():
                    submit = gr.Button("作答", variant="primary", elem_classes=["action-btn"])
                    restart = gr.Button("返回准备", elem_classes=["ghost-btn"])
                share = gr.Textbox(label="可分享成绩单", lines=12, visible=False, show_copy_button=True)

        outputs = [state, setup_col, play_col, battle, answer, scaffolds, submit, share, setup_msg]
        sample.change(load_sample, inputs=sample, outputs=abstract)
        start.click(start_game, inputs=[abstract, rounds, player], outputs=outputs)
        submit.click(answer_round, inputs=[answer, state], outputs=outputs)
        define_btn.click(use_define, inputs=answer, outputs=answer)
        experiment_btn.click(use_experiment, inputs=answer, outputs=answer)
        logic_btn.click(use_logic, inputs=answer, outputs=answer)
        restart.click(back_to_lobby, outputs=outputs)
    return demo


demo = build_demo()


if __name__ == "__main__":
    port = int(os.environ.get("GRADIO_SERVER_PORT") or os.environ.get("PORT") or "7860")
    demo.launch(
        server_name=os.environ.get("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=port,
        show_error=True,
    )
