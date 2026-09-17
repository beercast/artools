"""Tests for the local web launcher."""

from artools import web_launcher


def test_launcher_binds_loopback_and_uses_selected_port(monkeypatch, capsys) -> None:
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(web_launcher, "_serve", lambda host, port: calls.append((host, port)))

    assert web_launcher.main(["--port", "8765", "--no-browser"]) == 0

    assert calls == [("127.0.0.1", 8765)]
    assert "http://127.0.0.1:8765/" in capsys.readouterr().out


def test_launcher_uses_free_port_when_zero(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(web_launcher, "_free_port", lambda host: 43210)
    monkeypatch.setattr(web_launcher, "_serve", lambda host, port: calls.append((host, port)))

    assert web_launcher.main(["--port", "0", "--no-browser"]) == 0
    assert calls == [("127.0.0.1", 43210)]
