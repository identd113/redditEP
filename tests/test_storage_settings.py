import pytest

from edenprairie_news import storage


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    storage.init_db(path)
    return path


def test_get_setting_returns_default_when_unset(db_path):
    assert storage.get_setting("reddit_client_id", default=None, db_path=db_path) is None
    assert storage.get_setting("reddit_client_id", default="fallback", db_path=db_path) == "fallback"


def test_set_then_get_roundtrips(db_path):
    storage.set_setting("reddit_client_id", "abc123", db_path)
    assert storage.get_setting("reddit_client_id", db_path=db_path) == "abc123"


def test_set_setting_overwrites_existing_value(db_path):
    storage.set_setting("reddit_client_id", "first", db_path)
    storage.set_setting("reddit_client_id", "second", db_path)
    assert storage.get_setting("reddit_client_id", db_path=db_path) == "second"
