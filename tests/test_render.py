from game.engine import new_game, submit_answer
from game.mock_brain import MockBrain
from game.render import render_lobby, render_stage
from game.samples import SAMPLE_WARNING


def test_lobby_introduces_the_cast_and_mock_banner():
    html = render_lobby("演示模式 · 测试")
    for name in ("林知远", "周衡", "沈析"):
        assert name in html
    assert "演示模式 · 测试" in html
    assert "data:image/svg+xml" in html
    assert "答辩突袭" in html


def test_stage_escapes_player_text_and_shows_meters():
    abstract = "<script>alert(1)</script> 这是一段足够长的摘要，用来确认页面不会把标签当代码。"
    state = new_game(abstract, player="<b>小陈</b>", brain=MockBrain())
    state = submit_answer(state, "<img src=x onerror=alert(1)> 我不知道定义。", brain=MockBrain())
    html = render_stage(state)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert "&lt;b&gt;小陈" in html
    assert 'data-testid="hp-value"' in html
    assert 'data-testid="stress-value"' in html
    assert "破绽" in html


def test_report_contains_share_block_after_collapse():
    brain = MockBrain()
    state = new_game(SAMPLE_WARNING, brain=brain)
    for _ in range(4):
        state = submit_answer(state, "不知道", brain=brain)
    html = render_stage(state)
    assert 'data-testid="outcome"' in html
    assert "延毕警告" in html
    assert 'data-testid="share-preview"' in html
    assert "《答辩突袭》成绩单" in html
