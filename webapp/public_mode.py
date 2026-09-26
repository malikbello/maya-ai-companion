"""
Public mode — what changes when MAYA is served to strangers on the internet.

On the home device MAYA is a single-person companion: one health profile,
the owner's Spotify and Telegram accounts, a motion sensor, an SOS flow that
messages real contacts. None of that is safe to hand to an anonymous visitor,
so with MAYA_MODE=public the server:

  * drops every function that acts on the owner's accounts or hardware, both
    from the agent's tool list (so the model never offers them) and from the
    dispatcher (so a crafted request cannot reach them);
  * gives each voice session its own throwaway state directory, so one
    visitor's logged sleep or symptoms are never visible to the next;
  * meters sessions — per-IP rate, concurrency, length, and a daily budget of
    agent minutes — because every session spends paid speech credits.

The limits live in process memory. That is deliberate: the demo runs as one
instance, and a restart resetting the counters errs toward availability.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path

import health_memory
import user_manager

PUBLIC = os.getenv("MAYA_MODE", "personal").strip().lower() == "public"

# Functions that reach the owner's accounts, contacts or hardware.
PERSONAL_ONLY = frozenset({
    "trigger_emergency", "cancel_emergency", "set_doctor_contact", "set_health_emergency_contact",
    "send_telegram_message", "send_health_report_telegram", "check_telegram_status",
    "play_spotify", "play_spotify_artist", "pause_spotify", "resume_spotify", "close_spotify",
    "skip_track", "previous_track", "set_spotify_volume", "get_now_playing",
    "start_motion_monitoring", "stop_motion_monitoring", "get_motion_status", "set_motion_cooldown",
})


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        return default


LIMITS = {
    "session_seconds": _int_env("MAYA_SESSION_SECONDS", 180),
    "sessions_per_ip_hour": _int_env("MAYA_SESSIONS_PER_IP_HOUR", 4),
    "max_concurrent": _int_env("MAYA_MAX_CONCURRENT", 3),
    "daily_minutes": _int_env("MAYA_DAILY_MINUTES", 60),
}

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("MAYA_ALLOWED_ORIGINS", "").split(",") if o.strip()]


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Browsers always send Origin on a WebSocket handshake. Accept the page's
    own host, plus any explicitly allowed origins; refuse everything else so
    another site cannot embed a client that spends this deployment's credits."""
    if not PUBLIC:
        return True
    if not origin:
        return False
    if origin in ALLOWED_ORIGINS:
        return True
    bare = origin.split("://", 1)[-1]
    return bool(host) and bare == host


# ── session metering ─────────────────────────────────────────────────────────

class Gate:
    def __init__(self, limits: dict):
        self.limits = limits
        self._lock = threading.Lock()
        self._starts: dict[str, deque] = defaultdict(deque)
        self._active = 0
        self._day = time.strftime("%Y-%m-%d", time.gmtime())
        self._used_seconds = 0.0

    def _roll_day(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._day:
            self._day, self._used_seconds = today, 0.0

    def admit(self, ip: str) -> str | None:
        """Reserve a session slot, or return the reason it was refused."""
        with self._lock:
            self._roll_day()
            now = time.time()
            starts = self._starts[ip]
            while starts and now - starts[0] > 3600:
                starts.popleft()
            if self._used_seconds >= self.limits["daily_minutes"] * 60:
                return "MAYA has used today's demo time. Please come back tomorrow."
            if self._active >= self.limits["max_concurrent"]:
                return "MAYA is talking with other visitors right now. Please try again in a few minutes."
            if len(starts) >= self.limits["sessions_per_ip_hour"]:
                return "You have reached this hour's demo sessions. Please try again later."
            starts.append(now)
            self._active += 1
            return None

    def release(self, seconds: float):
        with self._lock:
            self._roll_day()
            self._active = max(0, self._active - 1)
            self._used_seconds += seconds

    def status(self) -> dict:
        with self._lock:
            self._roll_day()
            left = self.limits["daily_minutes"] * 60 - self._used_seconds
            return {"active": self._active, "daily_seconds_left": max(0, int(left))}


gate = Gate(LIMITS)


# ── per-session state ────────────────────────────────────────────────────────

_STATE_ROOT = Path(tempfile.gettempdir()) / "maya-sessions"
# The backend modules keep their file paths in module globals, so a session's
# function calls are serialised and the globals pointed at that session's
# directory for the duration of each call. Calls are short (a file write, or
# one HTTP request), and demo concurrency is capped, so the lock is cheap.
_state_lock = threading.Lock()


def new_session() -> str:
    sid = uuid.uuid4().hex
    (_STATE_ROOT / sid).mkdir(parents=True, exist_ok=True)
    return sid


def end_session(sid: str):
    shutil.rmtree(_STATE_ROOT / sid, ignore_errors=True)


@contextmanager
def session_state(sid: str | None):
    if not PUBLIC or sid is None:
        yield
        return
    root = _STATE_ROOT / sid
    with _state_lock:
        saved = (health_memory.FILE_NAME, user_manager.USERS_DIR, user_manager.user_manager.current_user)
        health_memory.FILE_NAME = str(root / "health_profile.json")
        user_manager.USERS_DIR = str(root / "users")
        user_manager.user_manager.current_user = user_manager.UserProfile("visitor")
        try:
            yield
        finally:
            health_memory.FILE_NAME, user_manager.USERS_DIR, user_manager.user_manager.current_user = saved


def blocked(name: str) -> bool:
    return PUBLIC and name in PERSONAL_ONLY


BLOCKED_REPLY = {
    "result": "That feature runs on MAYA's home device only; it is not part of the web demo.",
    "ui_type": "none",
    "ui_data": {},
}


def filter_settings(config: dict) -> dict:
    """Remove personal-only tools from the agent and tell it what the demo is."""
    if not PUBLIC:
        return config
    think = config["agent"]["think"]
    think["functions"] = [f for f in think["functions"] if f["name"] not in PERSONAL_ONLY]
    think["prompt"] += (
        " PUBLIC WEB DEMO: you are talking with a visitor trying MAYA in a browser. "
        "Spotify, Telegram, the motion sensor and the emergency SOS flow run on MAYA's home device and are not available here; "
        "if asked, say so briefly and offer what you can do: time, weather, reminders, alarms, health and mood logging, wellness score, health news and medication information. "
        "If the visitor describes a real emergency, tell them clearly to contact local emergency services now. "
        f"Sessions last about {LIMITS['session_seconds'] // 60} minutes and nothing the visitor says is kept afterwards."
    )
    return config
