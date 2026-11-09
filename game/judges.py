"""三位评委的人设。调度和界面都从这里取名字，避免各写一套。"""

from urllib.parse import quote

JUDGE_ORDER = ["concept", "experiment", "logic"]

JUDGES = {
    "concept": {
        "id": "concept",
        "name": "林知远",
        "role": "概念控教授",
        "emoji": "🧠",
        "monogram": "林",
        "motto": "概念站不住，后面全是空中楼阁。",
        "color": "#243864",
        "ink": "#f3eadb",
    },
    "experiment": {
        "id": "experiment",
        "name": "周衡",
        "role": "实验狂人",
        "emoji": "🧪",
        "monogram": "周",
        "motto": "没有对照的结论，只是感想。",
        "color": "#8a4b22",
        "ink": "#f8efe4",
    },
    "logic": {
        "id": "logic",
        "name": "沈析",
        "role": "逻辑杠精",
        "emoji": "📐",
        "monogram": "沈",
        "motto": "你上一句和这一句，我都抄下来了。",
        "color": "#1d4a43",
        "ink": "#f4faf7",
    },
}


def avatar_svg(judge_id: str) -> str:
    """花押印章：色环加姓。emoji 放在 HTML 里，SVG 负责形状。"""
    judge = JUDGES[judge_id]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<circle cx="32" cy="32" r="30" fill="{judge["color"]}"/>'
        f'<circle cx="32" cy="32" r="24" fill="none" stroke="{judge["ink"]}" '
        'stroke-width="1.6" opacity="0.85"/>'
        f'<path d="M32 8 L35 16 L32 14 L29 16 Z" fill="{judge["ink"]}" opacity="0.9"/>'
        f'<text x="32" y="42" text-anchor="middle" font-size="22" fill="{judge["ink"]}" '
        'font-family="WenQuanYi Micro Hei, Noto Sans SC, sans-serif">'
        f'{judge["monogram"]}</text></svg>'
    )


def avatar_src(judge_id: str) -> str:
    return "data:image/svg+xml;charset=utf-8," + quote(avatar_svg(judge_id))
