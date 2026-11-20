import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "edenprairie_news" / "web" / "static" / "style.css").read_text()


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rule(selector: str) -> str:
    start = CSS.index(selector + " {")
    return CSS[start:CSS.index("}", start)]


def _color(rule: str, prop: str) -> str:
    """The colour (#rgb or #rrggbb, returned as #rrggbb) in a declaration like `color: #fff` or `border: 2px solid #4a5568`."""
    m = re.search(rf"(?<![-\w]){prop}:[^;]*?(#[0-9a-fA-F]{{3}}(?:[0-9a-fA-F]{{3}})?)\b", rule)
    if not m:
        return ""
    c = m.group(1)
    return "#" + "".join(ch * 2 for ch in c[1:]) if len(c) == 4 else c


def test_every_button_style_is_readable_and_stands_out_from_the_page():
    page = _color(_rule("body"), "background")
    for selector, default_text in [("button", None), ("button.post", None), ("button.danger", None), ("button.secondary", None)]:
        rule = _rule(selector)
        base = _rule("button")
        background = _color(rule, "background") or _color(base, "background")
        text = _color(rule, "color") or _color(base, "color")
        border = _color(rule, "border") or _color(base, "border")
        assert _contrast(text, background) >= 4.5, (selector, "text on button")
        # the button must be visible against the page: by its fill, or (the white one) by a dark outline
        assert max(_contrast(background, page), _contrast(border, page) if border else 0) >= 3, (selector, "button on page")


def test_the_post_button_is_its_own_colour_and_the_templates_use_the_styles():
    assert _color(_rule("button.post"), "background") not in ("", _color(_rule("button"), "background"))
    index = (Path(__file__).resolve().parent.parent / "edenprairie_news" / "web" / "templates" / "index.html").read_text()
    assert index.count('class="post"') >= 1 and 'class="danger"' in index
