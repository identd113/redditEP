from edenprairie_news import storage
from edenprairie_news.config import RedditSettings, mod_queue_enabled


def _settings(**overrides):
    base = dict(
        client_id=None,
        client_secret=None,
        username=None,
        password=None,
        refresh_token=None,
        user_agent="ua",
        subreddit="edenprairie",
        sync_limit=50,
    )
    base.update(overrides)
    return RedditSettings(**base)


def test_is_configured_false_with_no_credentials():
    assert not _settings().is_configured


def test_is_configured_false_missing_client_credentials():
    assert not _settings(username="u", password="p").is_configured


def test_is_configured_true_with_username_password():
    assert _settings(client_id="id", client_secret="secret", username="u", password="p").is_configured


def test_is_configured_true_with_refresh_token():
    assert _settings(client_id="id", client_secret="secret", refresh_token="tok").is_configured


def test_is_configured_false_refresh_token_without_client_credentials():
    assert not _settings(refresh_token="tok").is_configured


def test_mod_queue_enabled_defaults_false(monkeypatch):
    monkeypatch.setattr(storage, "get_setting", lambda key, default=None, db_path=None: None)
    monkeypatch.delenv("ENABLE_MOD_QUEUE", raising=False)
    assert mod_queue_enabled() is False


def test_mod_queue_enabled_true_from_db_setting(monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_setting",
        lambda key, default=None, db_path=None: "true" if key == "mod_queue_enabled" else None,
    )
    assert mod_queue_enabled() is True


def test_mod_queue_enabled_true_from_env_fallback(monkeypatch):
    monkeypatch.setattr(storage, "get_setting", lambda key, default=None, db_path=None: None)
    monkeypatch.setenv("ENABLE_MOD_QUEUE", "true")
    assert mod_queue_enabled() is True
