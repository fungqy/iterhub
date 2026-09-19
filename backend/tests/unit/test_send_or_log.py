"""send_or_log 在 PUSH_ENABLED 开关下的两种行为"""

import logging

from util import qywx


def test_push_disabled_logs_only(monkeypatch, caplog):
    monkeypatch.setattr(qywx, "PUSH_ENABLED", False)

    called = {"post": False}

    def fake_post(robot_key, message):
        called["post"] = True

    monkeypatch.setattr(qywx, "post", fake_post)

    with caplog.at_level(logging.INFO, logger="QyWx"):
        qywx.send_or_log("robot-key-12345678", "## hello")

    assert called["post"] is False
    assert any("PUSH_DISABLED" in r.message for r in caplog.records)


def test_push_enabled_calls_post(monkeypatch):
    monkeypatch.setattr(qywx, "PUSH_ENABLED", True)

    calls = []

    def fake_post(robot_key, message):
        calls.append((robot_key, message))

    monkeypatch.setattr(qywx, "post", fake_post)

    qywx.send_or_log("robot-key-12345678", "## hello")

    assert calls == [("robot-key-12345678", "## hello")]


def test_empty_message_is_noop(monkeypatch):
    monkeypatch.setattr(qywx, "PUSH_ENABLED", True)

    calls = []
    monkeypatch.setattr(qywx, "post", lambda r, m: calls.append((r, m)))

    qywx.send_or_log("robot-key", None)
    qywx.send_or_log("robot-key", "")

    assert calls == []
