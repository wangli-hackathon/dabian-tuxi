"""密钥开关、JSON 兜底，以及在线评委失败时退回演示题库。"""

import pytest

from game.engine import new_game, submit_answer
from game.llm import LiveBrain, build_brain, resolve_settings
from game.samples import SAMPLE_WARNING
from game.textutil import parse_json_object


def test_missing_key_is_mock_and_uses_modelscope_defaults():
    settings = resolve_settings({})
    assert settings.mode == "mock"
    assert settings.api_key == ""
    assert settings.base_url == "https://api-inference.modelscope.cn/v1/"
    assert settings.model == "Qwen/Qwen2.5-72B-Instruct"
    assert build_brain({}).mode == "mock"


def test_modelscope_key_selects_live_qwen():
    settings = resolve_settings({"MODELSCOPE_API_KEY": "ms-abc"})
    assert settings.mode == "live"
    assert settings.api_key == "ms-abc"
    assert settings.key_source == "MODELSCOPE_API_KEY"
    assert settings.base_url == "https://api-inference.modelscope.cn/v1/"
    assert settings.model == "Qwen/Qwen2.5-72B-Instruct"


def test_modelscope_key_wins_over_dashscope():
    settings = resolve_settings(
        {"MODELSCOPE_API_KEY": "ms-abc", "DASHSCOPE_API_KEY": "sk-dash"}
    )
    assert settings.key_source == "MODELSCOPE_API_KEY"
    assert "modelscope.cn" in settings.base_url


def test_dashscope_only_switches_endpoint_and_model_name():
    settings = resolve_settings({"DASHSCOPE_API_KEY": "sk-dash"})
    assert settings.mode == "live"
    assert settings.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1/"
    assert settings.model == "qwen2.5-72b-instruct"


def test_explicit_override_and_force_mock():
    settings = resolve_settings(
        {
            "MODELSCOPE_API_KEY": "ms-abc",
            "MODELSCOPE_BASE_URL": "https://example.test/v1",
            "MODELSCOPE_MODEL": "Qwen/Qwen2.5-14B-Instruct",
        }
    )
    assert settings.base_url == "https://example.test/v1/"
    assert settings.model == "Qwen/Qwen2.5-14B-Instruct"
    forced = resolve_settings({"MODELSCOPE_API_KEY": "ms-abc", "DABIAN_MOCK": "1"})
    assert forced.mode == "mock"
    assert forced.api_key == ""
    assert build_brain({"MODELSCOPE_API_KEY": "mock"}).mode == "mock"


def test_placeholder_keys_do_not_go_live():
    for key in ("", "mock", "offline", "NONE"):
        settings = resolve_settings({"MODELSCOPE_API_KEY": key})
        assert settings.mode == "mock"


def test_parse_json_accepts_fences_and_trailing_commas():
    assert parse_json_object('```json\n{"a": 1,}\n```') == {"a": 1}
    assert parse_json_object('好的 {"question": "为什么", "n": 2}')["question"] == "为什么"


def test_parse_json_rejects_garbage():
    with pytest.raises(ValueError):
        parse_json_object("评委今天不想说话")


def test_live_failure_falls_back_without_leaking_the_key():
    settings = resolve_settings({"MODELSCOPE_API_KEY": "ms-secret-key"})
    brain = LiveBrain(settings)

    def explode(*_args, **_kwargs):
        raise TimeoutError("simulated outage")

    brain._complete = explode
    state = new_game(SAMPLE_WARNING, player="小陈", brain=brain)
    assert state["mode"] == "live"
    assert state["pending"]["source"] == "fallback"
    assert "演示题库" in state["notice"]
    assert "ms-secret-key" not in state["notice"]
    assert "ms-secret-key" not in state["pending"]["question"]
    state = submit_answer(state, "不知道", brain=brain)
    assert state["cursor"] == 1
    assert state["turns"][0]["hp_delta"] == -26
    blob = str(state["log"]) + state.get("notice", "")
    assert "ms-secret-key" not in blob
