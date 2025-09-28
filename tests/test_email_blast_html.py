import os

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.main import _plain_text_to_html


def test_plain_text_to_html_linkification_and_escaping():
    html = _plain_text_to_html("Visit https://example.com & stay <safe>")
    assert '<a href="https://example.com">https://example.com</a>' in html
    assert "&amp; stay" in html
    assert "&lt;safe&gt;" in html
