import json
import logging
import os

os.environ.setdefault("REDIS_URL", "redis://localhost/0")
os.environ.setdefault("OPENAI_API_KEY", "test")

import worker


class DummyRedis:
    def __init__(self, data):
        self.data = data

    def scan_iter(self, pattern="*"):
        for key in self.data:
            yield key

    def get(self, key):
        return self.data.get(key)


def test_weekly_summary_logs_success(monkeypatch, caplog):
    user_data = {"user:career@example.com": json.dumps({"role": "career"})}
    dummy = DummyRedis(user_data)
    monkeypatch.setattr(worker, "redis_client", dummy)

    sent = {}

    def fake_send(email):
        sent["email"] = email
        return True

    monkeypatch.setattr(worker, "send_weekly_summary", fake_send)

    caplog.set_level(logging.INFO)
    worker.weekly_summary_worker()

    assert "Sending weekly summary to career@example.com" in caplog.text
    assert "Successfully sent weekly summary to career@example.com" in caplog.text
    assert sent["email"] == "career@example.com"


def test_weekly_summary_logs_error(monkeypatch, caplog):
    user_data = {"user:career@example.com": json.dumps({"role": "career"})}
    dummy = DummyRedis(user_data)
    monkeypatch.setattr(worker, "redis_client", dummy)

    def fake_send(email):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "send_weekly_summary", fake_send)

    caplog.set_level(logging.INFO)
    worker.weekly_summary_worker()

    assert "Failed to send weekly summary to career@example.com" in caplog.text
