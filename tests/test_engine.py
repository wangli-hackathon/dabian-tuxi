"""规则、破绽、记忆和结局。全程使用演示评委，不访问网络。"""

import copy

import pytest

from game.engine import new_game, submit_answer
from game.judges import JUDGE_ORDER
from game.mock_brain import MockBrain
from game.samples import DEMO_ANSWERS, SAMPLE_ATTENTION, SAMPLE_BOOKS, SAMPLE_WARNING
from game.scoring import build_report, normalize_verdict, share_text
from game.textutil import clip_quote

GOOD = (
    "我先给操作化定义：核心概念是指可被重复观测的行为模式，它和邻近概念的边界在于是否保留时间顺序。"
    "例如把一周提交次数定义成指标，正例是连续四周的提交记录，反例是只看期末成绩。"
    "因为前提写清楚了，所以推论才推得出来。实验上有对照组，样本 120 人，基线用平均分，数据可以复现。"
)
WEAK = "我觉得这个想法很有意义，应该可以帮助学生，后面再慢慢补充。"


def play(abstract, answers, rounds=6, player="小陈"):
    brain = MockBrain()
    state = new_game(abstract, total_rounds=rounds, player=player, brain=brain)
    for answer in answers:
        if state["status"] != "playing":
            break
        state = submit_answer(state, answer, brain=brain)
    return state


def test_short_abstract_is_rejected():
    with pytest.raises(ValueError):
        new_game("太短了", brain=MockBrain())


def test_rounds_are_clamped():
    assert new_game(SAMPLE_WARNING, total_rounds=1, brain=MockBrain())["total_rounds"] == 4
    assert new_game(SAMPLE_WARNING, total_rounds=99, brain=MockBrain())["total_rounds"] == 8


def test_opening_uses_three_distinct_judges():
    state = new_game(SAMPLE_WARNING, brain=MockBrain())
    entered = [item["judge"] for item in state["log"] if item["kind"] == "enter"]
    assert entered == JUDGE_ORDER
    assert state["pending"]["judge"] == "concept"
    assert state["pending"]["referenced_round"] is None
    assert "我还记得你第" not in state["pending"]["question"]


def test_same_opening_is_deterministic_and_abstract_changes_it():
    first = new_game(SAMPLE_WARNING, brain=MockBrain())["pending"]["question"]
    second = new_game(SAMPLE_WARNING, brain=MockBrain())["pending"]["question"]
    other = new_game(SAMPLE_BOOKS, brain=MockBrain())["pending"]["question"]
    assert first == second
    assert first != other


def test_memory_quote_is_a_real_slice_of_the_previous_answer():
    state = new_game(SAMPLE_WARNING, brain=MockBrain())
    answer = "甲乙丙丁独特前缀，后面我再解释定义和边界。"
    state = submit_answer(state, answer, brain=MockBrain())
    quote = clip_quote(answer)
    assert quote in state["pending"]["question"]
    assert state["pending"]["referenced_round"] == 1
    assert "我还记得你第1轮说过" in state["pending"]["question"]


def test_good_answers_rotate_all_three_judges_and_pass():
    state = play(SAMPLE_WARNING, [GOOD] * 6)
    assert [turn["judge"] for turn in state["turns"]] == [
        "concept",
        "experiment",
        "logic",
        "concept",
        "experiment",
        "logic",
    ]
    assert state["status"] == "passed"
    assert state["hp"] == 100
    assert state["weaknesses"] == []
    assert share_text(state).startswith("《答辩突袭》成绩单")
    assert "答辩通过" in share_text(state)


def test_silence_and_dodge_collapse_into_yanbi_warning():
    state = play(SAMPLE_WARNING, ["不知道"] * 6)
    assert state["status"] == "failed"
    assert state["hp"] == 0
    assert state["cursor"] == 4
    report = build_report(state)
    assert report["outcome"] == "延毕警告"
    assert report["grade"] == "不及格"
    assert "延毕警告" in share_text(state)


def test_blank_answer_counts_as_silence():
    state = new_game(SAMPLE_ATTENTION, brain=MockBrain())
    state = submit_answer(state, "   ", brain=MockBrain())
    assert state["turns"][0]["answer"] == "（沉默）"
    assert state["turns"][0]["hp_delta"] == -26
    assert state["hp"] == 74


def test_weakness_is_chased_after_the_intro_round_and_can_be_repaired():
    brain = MockBrain()
    state = new_game(SAMPLE_WARNING, brain=brain)
    state = submit_answer(state, GOOD, brain=brain)
    state = submit_answer(state, WEAK, brain=brain)
    created = [item for item in state["weaknesses"] if item["judge"] == "experiment" and not item["resolved"]]
    assert created
    assert state["pending"]["judge"] == "logic"
    assert state["pending"]["targets_weakness_id"] is None
    state = submit_answer(state, GOOD, brain=brain)
    target = state["pending"]["targets_weakness_id"]
    assert target
    tag = next(item["tag"] for item in state["weaknesses"] if item["id"] == target)
    assert tag in state["pending"]["question"]
    quote = clip_quote(WEAK)
    assert quote in state["pending"]["question"]
    state = submit_answer(state, GOOD, brain=brain)
    repaired = next(item for item in state["weaknesses"] if item["id"] == target)
    assert repaired["resolved"] is True


def test_contradiction_is_remembered_as_a_weakness():
    brain = MockBrain()
    state = new_game(SAMPLE_WARNING, brain=brain)
    state = submit_answer(
        state,
        "我认为提交次数和成绩正相关，因为高频练习会把分数抬起来。定义上这是行为与结果的相关。",
        brain=brain,
    )
    state = submit_answer(state, GOOD, brain=brain)
    state = submit_answer(state, "我改口：提交次数和成绩是负相关。", brain=brain)
    assert any(item["tag"] == "前后说法不一致" for item in state["weaknesses"])
    assert state["turns"][-1]["hp_delta"] <= -16


def test_submit_does_not_mutate_the_previous_state():
    brain = MockBrain()
    original = new_game(SAMPLE_ATTENTION, brain=brain)
    snapshot = copy.deepcopy(original)
    updated = submit_answer(original, "不知道", brain=brain)
    assert original["cursor"] == snapshot["cursor"] == 0
    assert original["hp"] == 100
    assert updated["cursor"] == 1
    assert updated["hp"] < 100


def test_two_full_matches_are_identical():
    answers = ["不知道", GOOD, WEAK, "随便", GOOD, GOOD]
    left = play(SAMPLE_BOOKS, answers, player="甲")
    right = play(SAMPLE_BOOKS, answers, player="甲")
    assert left["hp"] == right["hp"]
    assert [turn["question"] for turn in left["turns"]] == [turn["question"] for turn in right["turns"]]
    assert left["weaknesses"] == right["weaknesses"]
    assert share_text(left) == share_text(right)


def test_scripted_demo_survives_and_resolves_a_weakness():
    state = play(SAMPLE_WARNING, DEMO_ANSWERS)
    assert state["status"] == "passed"
    assert 0 < state["hp"] < 100
    assert any(item["resolved"] for item in state["weaknesses"])
    assert {turn["judge"] for turn in state["turns"]} == set(JUDGE_ORDER)
    text = share_text(state)
    assert "答辩人：小陈" in text
    assert "概念" in text and "实验" in text and "逻辑" in text


def test_hp_never_exceeds_max_when_healing():
    state = play(SAMPLE_WARNING, [GOOD] * 6)
    assert all(0 <= turn["hp_after"] <= 100 for turn in state["turns"])


def test_grade_bands_and_failed_override():
    def fake(status, score, hp):
        return {
            "status": status,
            "scores": {"concept": score, "experiment": score, "logic": score},
            "hp": hp,
            "weaknesses": [],
            "turns": [],
            "cursor": 6,
            "total_rounds": 6,
            "title": "测试课题",
            "player": "小陈",
        }

    assert build_report(fake("passed", 90, 90))["grade"] == "优秀"
    assert build_report(fake("passed", 84, 84))["grade"] == "良好"
    assert build_report(fake("passed", 72, 72))["grade"] == "良好"
    assert build_report(fake("passed", 71, 71))["grade"] == "及格"
    assert build_report(fake("passed", 50, 50))["grade"] == "险过"
    failed = build_report(fake("failed", 90, 0))
    assert failed["outcome"] == "延毕警告"
    assert failed["grade"] == "不及格"


def test_normalize_clamps_wild_model_damage():
    mild = normalize_verdict({"quality": "ok", "hp_delta": -100, "reaction": "还行"})
    assert mild["hp_delta"] == -6
    wild = normalize_verdict(
        {"quality": "collapse", "hp_delta": 30, "resolved_weakness_ids": ["w1"]}
    )
    assert wild["hp_delta"] == -26
    assert wild["resolved_weakness_ids"] == []
    healed = normalize_verdict({"quality": "strong", "hp_delta": 6})
    assert healed["hp_delta"] == 6


def test_player_name_is_trimmed():
    state = new_game(SAMPLE_WARNING, player="  小陈\n同学  ", brain=MockBrain())
    assert state["player"] == "小陈 同学"
    state = new_game(SAMPLE_WARNING, player="", brain=MockBrain())
    assert state["player"] == "同学"
