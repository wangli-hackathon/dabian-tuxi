"""命令行打一局演示模式，用来在没开浏览器时核对结局。"""

from __future__ import annotations

from game.engine import new_game, submit_answer
from game.judges import JUDGES
from game.mock_brain import MockBrain
from game.samples import DEMO_ANSWERS, SAMPLES, SAMPLE_WARNING
from game.scoring import share_text


def main() -> int:
    brain = MockBrain()
    state = new_game(SAMPLE_WARNING, total_rounds=6, player="同学", brain=brain)
    print(f"课题：{state['title']}")
    print(f"示例：{SAMPLES[0][0]} · 演示模式")
    for answer in DEMO_ANSWERS:
        if state["status"] != "playing":
            break
        pending = state["pending"]
        judge = JUDGES[pending["judge"]]
        print(f"\n第 {pending['round']} 轮 · {judge['role']} {judge['name']}")
        print(pending["question"])
        state = submit_answer(state, answer, brain=brain)
        turn = state["turns"][-1]
        print(f"—— {turn['reaction']}（体力 {turn['hp_delta']:+d} → {state['hp']}）")
    print("\n" + share_text(state))
    print(f"\n结局状态：{state['status']}")
    return 0 if state["status"] in {"passed", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
