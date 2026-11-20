import pytest

from edenprairie_news import storage


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    # Point at a nonexistent feeds.yaml so init_db's one-time seed no-ops --
    # these tests want an empty feeds table to start from, not the real
    # project's config/feeds.yaml contents.
    monkeypatch.setattr(storage, "FEEDS_PATH", tmp_path / "no-such-feeds.yaml")
    path = tmp_path / "test.db"
    storage.init_db(path)
    return path


def test_add_and_list_feeds(db_path):
    storage.add_feed("Test Feed", "https://example.com/rss", ["needs-filter"], "default", db_path)
    feeds = storage.list_feeds(db_path)
    assert len(feeds) == 1
    assert feeds[0].name == "Test Feed"
    assert feeds[0].url == "https://example.com/rss"
    assert feeds[0].tags == ["needs-filter"]
    assert feeds[0].parser == "default"
    assert feeds[0].id is not None


def test_delete_feed(db_path):
    storage.add_feed("Test Feed", "https://example.com/rss", [], "default", db_path)
    feed_id = storage.list_feeds(db_path)[0].id
    storage.delete_feed(feed_id, db_path)
    assert storage.list_feeds(db_path) == []


def test_init_db_seeds_feeds_from_yaml_once(tmp_path, monkeypatch):
    yaml_path = tmp_path / "feeds.yaml"
    yaml_path.write_text(
        "feeds:\n"
        "  - name: Seeded Feed\n"
        "    url: https://example.com/seeded\n"
        "    tags: []\n"
        "    parser: default\n"
    )
    monkeypatch.setattr(storage, "FEEDS_PATH", yaml_path)

    db_path = tmp_path / "test.db"
    storage.init_db(db_path)
    feeds = storage.list_feeds(db_path)
    assert len(feeds) == 1
    assert feeds[0].name == "Seeded Feed"

    # A feed added by hand afterward must survive re-running init_db (no re-seed
    # once the table is non-empty).
    storage.add_feed("Manual Feed", "https://example.com/manual", [], "default", db_path)
    storage.init_db(db_path)
    names = {f.name for f in storage.list_feeds(db_path)}
    assert names == {"Seeded Feed", "Manual Feed"}
