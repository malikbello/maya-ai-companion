"""
Public-mode guarantees: what an anonymous visitor can and cannot reach.

Runs without network or credentials: the Deepgram URL is pointed at a closed
local port, so a voice session fails fast after admission and metering.
    MAYA_MODE=public python -m pytest webapp/tests -q
"""

import os
import sys
from pathlib import Path

os.environ["MAYA_MODE"] = "public"
os.environ["MAYA_SESSIONS_PER_IP_HOUR"] = "2"
os.environ["DEEPGRAM_API_KEY"] = "test-key-not-real"

ROOT = Path(__file__).resolve().parents[2]
# only the repo root, exactly as `uvicorn webapp.server:app` sees it
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from webapp import server  # noqa: E402  (puts ai_companion/ on the path)
import public_mode as pm  # noqa: E402

client = TestClient(server.app)


def test_health_and_config():
    assert client.get("/health").json() == {"status": "ok"}
    cfg = client.get("/config").json()
    assert cfg["mode"] == "public" and cfg["session_seconds"] > 0


def test_security_headers():
    h = client.get("/").headers
    assert "script-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"


def test_no_api_docs_in_public_mode():
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("name", ["trigger_emergency", "send_telegram_message", "play_spotify", "get_time"])
def test_function_endpoint_closed(name):
    r = client.post("/function", json={"name": name, "args": {}})
    assert r.status_code == 403


def test_lyrics_closed():
    assert client.get("/lyrics?artist=a&title=b").status_code == 403


def test_agent_never_sees_personal_tools():
    with pm.session_state(pm.new_session()):
        cfg = pm.filter_settings(server.build_settings_config())
    names = {f["name"] for f in cfg["agent"]["think"]["functions"]}
    assert not names & pm.PERSONAL_ONLY
    assert {"get_time", "log_sleep", "get_wellness_score"} <= names
    assert "PUBLIC WEB DEMO" in cfg["agent"]["think"]["prompt"]


def test_dispatcher_refuses_personal_tools():
    for name in pm.PERSONAL_ONLY:
        assert server._run_in_session("x", name, {}) == pm.BLOCKED_REPLY


def test_sessions_do_not_share_state():
    a, b = pm.new_session(), pm.new_session()
    server._run_in_session(a, "log_sleep", {"hours": 3})
    server._run_in_session(a, "set_name", {"name": "Ada"})
    with pm.session_state(b):
        import health_memory
        import user_manager
        assert health_memory.load_profile()["sleep_log"] == []
        assert user_manager.get_current_user().get_name() == "User"
    with pm.session_state(a):
        assert health_memory.load_profile()["sleep_log"][-1]["hours"] == 3
    pm.end_session(a)
    pm.end_session(b)
    # nothing written to the repo's own state files
    assert not (ROOT / "users" / "visitor").exists()


def test_websocket_rejects_foreign_origin():
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_websocket_rate_limit(monkeypatch):
    pm.gate._starts.clear()
    monkeypatch.setattr(server, "_proxy", _fake_proxy)
    ok = {"origin": "http://testserver"}
    for _ in range(2):
        with client.websocket_connect("/ws", headers=ok) as ws:
            assert ws.receive_json()["type"] == "Ready"
    with client.websocket_connect("/ws", headers=ok) as ws:
        msg = ws.receive_json()
    assert msg["type"] == "Limit" and "hour" in msg["message"]
    assert pm.gate.status()["active"] == 0  # every admitted slot was released


async def _fake_proxy(browser_ws, key, sid):
    await browser_ws.send_json({"type": "Ready"})
    await browser_ws.close()


def test_gate_daily_budget_and_concurrency():
    g = pm.Gate({"session_seconds": 60, "sessions_per_ip_hour": 99, "max_concurrent": 1, "daily_minutes": 1})
    assert g.admit("1.1.1.1") is None
    assert "other visitors" in g.admit("2.2.2.2")
    g.release(61)
    assert "today" in g.admit("3.3.3.3")


def test_forecast_gives_the_model_every_day(monkeypatch):
    import function_map

    days = [
        {"date": f"2026-10-0{i}", "day_name": n, "is_today": i == 1, "description": d, "temp_min": 24, "temp_max": 30, "rain_chance": r, "wind_speed": 3.1}
        for i, (n, d, r) in enumerate([("Monday", "light rain", 80), ("Tuesday", "clear sky", 5), ("Wednesday", "overcast", 30)], start=1)
    ]
    monkeypatch.setattr(function_map, "_forecast_raw", lambda city: {"city": city, "country": "NG", "days": days})
    out = server._run_in_session(pm.new_session(), "get_weather_forecast", {"city": "Ibadan"})
    assert out["ui_type"] == "forecast" and out["ui_data"]["city"] == "Ibadan"
    assert "Tuesday" in out["result"] and "5% chance of rain" in out["result"] and "80% chance of rain" in out["result"]


def test_due_reminders_fire_once_per_session():
    from datetime import datetime, timedelta

    a, b = pm.new_session(), pm.new_session()
    with pm.session_state(a):
        import user_manager

        past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        user_manager.get_current_user().add_reminder({"datetime": past, "message": "Take blood pressure medicine", "done": False})
    assert server._due_reminders(b) == []
    assert server._due_reminders(a) == ["Take blood pressure medicine"]
    assert server._due_reminders(a) == []
    pm.end_session(a)
    pm.end_session(b)


def test_message_doctor_is_personal_only_and_needs_a_doctor_chat(monkeypatch):
    assert "message_doctor" in pm.PERSONAL_ONLY
    import telegram_service

    monkeypatch.setattr(telegram_service, "DOCTOR_CHAT_ID", None)
    assert telegram_service.message_doctor("My blood pressure has been high")["sent"] is False
    sent = {}
    monkeypatch.setattr(telegram_service, "BOT_TOKEN", "x")
    monkeypatch.setattr(telegram_service, "DOCTOR_CHAT_ID", "42")
    monkeypatch.setattr(telegram_service, "send_telegram_message", lambda body, chat_id=None: sent.update(body=body, chat_id=chat_id) or True)
    out = telegram_service.message_doctor("My blood pressure has been high", "Malik")
    assert out["sent"] and sent["chat_id"] == "42"
    assert sent["body"].startswith("Message from Malik, sent by MAYA:") and sent["body"].endswith("My blood pressure has been high")


def test_agent_knows_the_saved_name_and_city():
    sid = pm.new_session()
    server._run_in_session(sid, "set_name", {"name": "Malik"})
    server._run_in_session(sid, "set_location", {"city": "Lagos"})
    with pm.session_state(sid):
        prompt = server.build_settings_config()["agent"]["think"]["prompt"]
    assert "The user's name is Malik." in prompt and "lives in Lagos" in prompt
    pm.end_session(sid)
