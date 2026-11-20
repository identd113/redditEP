import glob
import json
import re
from pathlib import Path

from edenprairie_news.web import app as web
from edenprairie_news.web import help_texts

TEMPLATES = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "edenprairie_news" / "web" / "templates" / "*.html")))


def _buttons():
    """(template, label, data-help-key) for every <button> in the templates; Jinja expressions inside become '...'."""
    for path in TEMPLATES:
        text = Path(path).read_text()
        for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", text, re.S):
            label = re.sub(r"\s+", " ", re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "…", m.group(2))).strip()
            key = re.search(r'data-help-key="([^"]+)"', m.group(1))
            yield Path(path).name, label, key.group(1) if key else None


def _covered(label, key):
    k = key or label
    return k in help_texts.EXACT or any(k.startswith(p) for p in help_texts.PREFIX)


def test_every_button_in_every_template_has_a_description():
    missing = [(t, label) for t, label, key in _buttons() if not _covered(label, key)]
    assert missing == [], f"buttons without help text: {missing}"


def test_the_mod_queue_buttons_that_act_on_reddit_say_so():
    for _, label, key in _buttons():
        pass
    mod = [(label, key) for t, label, key in _buttons() if t == "modqueue.html"]
    assert mod and all(key and key.startswith("Reddit: ") for _, key in mod)
    for key in ("Reddit: Approve", "Reddit: Remove", "Reddit: Remove as spam"):
        assert "Reddit itself" in help_texts.EXACT[key]


def test_no_description_is_unused_or_empty():
    labels = {key or label for _, label, key in _buttons()}
    for k, v in help_texts.EXACT.items():
        assert v.strip() and (k in labels), f"unused or empty help text: {k}"


def test_the_page_carries_the_descriptions_and_the_script_that_adds_the_i():
    web.app.config["TESTING"] = True
    html = web.app.test_client().get("/config").get_data(as_text=True)
    m = re.search(r'<script id="button-help" type="application/json">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1))
    assert data["exact"]["Remove"] == help_texts.EXACT["Remove"] and "Remove the " in data["prefix"]
    assert 'className = "info"' in html and 'insertAdjacentElement("afterend"' in html
