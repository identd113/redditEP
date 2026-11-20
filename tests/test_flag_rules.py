from edenprairie_news.flag_rules import compute_flags


def test_flags_missing_flair_and_reports():
    post = {"flair": None, "num_reports": 2}
    assert compute_flags(post) == ["no_flair", "reported"]


def test_no_flags_when_clean():
    post = {"flair": "Announcement", "num_reports": 0}
    assert compute_flags(post) == []


def test_flags_missing_keys_default_safely():
    assert compute_flags({}) == ["no_flair"]
