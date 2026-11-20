from edenprairie_news import config
from edenprairie_news.config import WebConfig


def test_links_for_other_devices_use_the_lan_address_not_loopback(monkeypatch):
    monkeypatch.setattr(WebConfig, "host", "0.0.0.0")
    monkeypatch.setattr(WebConfig, "port", "1981")
    monkeypatch.setattr(config, "_lan_address", lambda: "192.0.2.10")
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    assert WebConfig.base_url() == "http://192.0.2.10:1981"


def test_an_explicit_base_url_wins_and_a_specific_host_is_used_as_is(monkeypatch):
    monkeypatch.setattr(WebConfig, "host", "0.0.0.0")
    monkeypatch.setenv("WEB_BASE_URL", "http://newsbox.local:1981/")
    assert WebConfig.base_url() == "http://newsbox.local:1981"
    monkeypatch.delenv("WEB_BASE_URL")
    monkeypatch.setattr(WebConfig, "host", "192.0.2.10")
    monkeypatch.setattr(WebConfig, "port", "1981")
    assert WebConfig.base_url() == "http://192.0.2.10:1981"


def test_lan_address_falls_back_to_loopback_when_there_is_no_network(monkeypatch):
    import socket

    class NoNet:
        def __enter__(self):
            raise OSError("no route")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(socket, "socket", lambda *a, **k: NoNet())
    assert config._lan_address() == "127.0.0.1"


def test_pages_carry_the_mobile_viewport_tag():
    from edenprairie_news.web import app as web

    web.app.config["TESTING"] = True
    html = web.app.test_client().get("/config").get_data(as_text=True)
    assert 'name="viewport"' in html and "width=device-width" in html
