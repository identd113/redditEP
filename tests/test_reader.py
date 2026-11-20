from edenprairie_news.reader import _extract_image


def test_extract_image_prefers_media_thumbnail():
    entry = {
        "media_thumbnail": [{"url": "https://example.com/thumb.jpg"}],
        "media_content": [{"url": "https://example.com/content.jpg", "medium": "image"}],
    }
    assert _extract_image(entry) == "https://example.com/thumb.jpg"


def test_extract_image_falls_back_to_media_content():
    entry = {"media_content": [{"url": "https://example.com/content.jpg", "medium": "image"}]}
    assert _extract_image(entry) == "https://example.com/content.jpg"


def test_extract_image_falls_back_to_image_enclosure():
    entry = {"links": [{"rel": "enclosure", "type": "image/jpeg", "href": "https://example.com/e.jpg"}]}
    assert _extract_image(entry) == "https://example.com/e.jpg"


def test_extract_image_falls_back_to_img_tag_in_summary():
    entry = {"summary": '<p>Story <img src="https://example.com/inline.jpg"> more text</p>'}
    assert _extract_image(entry) == "https://example.com/inline.jpg"


def test_extract_image_returns_none_when_nothing_available():
    entry = {"summary": "<p>No image here</p>"}
    assert _extract_image(entry) is None
