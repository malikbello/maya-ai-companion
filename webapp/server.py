"""
MAYA Web App — FastAPI WebSocket Proxy Server
Bridges browser audio <-> Deepgram Voice Agent.
Executes all function calls server-side (API keys never reach the browser).

Run from project root:
  cd AI_Companion
  cleanenv/Scripts/python.exe -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000 --reload

Or directly:
  python webapp/server.py
"""

import asyncio
import json
import time
import logging
import os
import sys
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
AI_DIR = Path(__file__).parent.parent / "ai_companion"
sys.path.insert(0, str(AI_DIR))
# sibling modules (function_map, public_mode) when run as webapp.server
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(AI_DIR / ".env")

import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from function_map import run_function, build_settings_config
import public_mode as pm
from pydantic import BaseModel
import urllib.request
import urllib.parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("MAYA-Web")

app = FastAPI(title="MAYA Web", docs_url=None if pm.PUBLIC else "/docs", redoc_url=None, openapi_url=None if pm.PUBLIC else "/openapi.json")
# The page is served from this same origin, so public mode needs no CORS at all.
if not pm.PUBLIC:
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; media-src 'self' blob:; "
    "worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    if pm.PUBLIC:
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _client_ip(scope_headers, fallback: str) -> str:
    # Behind the host's proxy the socket peer is the proxy; the first
    # X-Forwarded-For hop is the visitor.
    fwd = scope_headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or fallback


# ── /config — what the page should show about this deployment ────────────────
@app.get("/config")
async def config():
    if not pm.PUBLIC:
        return {"mode": "personal"}
    return {
        "mode": "public",
        "session_seconds": pm.LIMITS["session_seconds"],
        **pm.gate.status(),
    }

# ── /health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


# ── /function — REST endpoint for direct UI function calls (Spotify controls etc.)
class FnRequest(BaseModel):
    name: str
    args: dict = {}
    function_call_id: str = ""

@app.post("/function")
async def call_function(req: FnRequest):
    # Public mode has no session outside the voice socket, and every UI
    # shortcut that uses this endpoint drives a personal integration.
    if pm.PUBLIC:
        return JSONResponse(pm.BLOCKED_REPLY, status_code=403)
    try:
        result = run_function(req.name, req.args)
        return result
    except Exception as exc:
        return {"result": str(exc), "ui_type": "none", "ui_data": {}}


# ── /lyrics — fetch lyrics for currently playing (or given) track ─────────────
@app.get("/lyrics")
async def get_lyrics(artist: str = "", title: str = ""):
    """
    Multi-source lyrics lookup.  Returns lrc_lines (timestamps) when available
    so the frontend can advance the glow in sync with the song.
    """
    if pm.PUBLIC:
        return JSONResponse({"found": False, "reason": "unavailable"}, status_code=403)
    loop = asyncio.get_event_loop()
    try:
        # Resolve track from Spotify if not supplied
        if not artist or not title:
            from spotify_service import get_now_playing_structured
            info = await loop.run_in_executor(None, get_now_playing_structured)
            if not info.get("is_playing"):
                return JSONResponse({"found": False, "reason": "nothing_playing"})
            artist = info["artist"]
            title  = info["track"]

        track_clean  = title.strip()
        artist_clean = artist.strip()
        query        = f"{track_clean} {artist_clean}"

        def _parse_lrc(raw: str):
            """Parse LRC into [{ms, text}] sorted by time. Returns None if no timestamps found."""
            import re as _re
            pat = _re.compile(r'\[(\d{2}):(\d{2})[.:](\d{2,3})\](.*)')
            # Purely-instrumental marker characters — skip these as lyric lines
            _instrumental = _re.compile(r'^[♪♫~🎵🎶\-\s]+$')
            lines = []
            for line in raw.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
                m = pat.match(line.strip())
                if m:
                    mins, secs, cs, text = m.groups()
                    ms   = int(mins)*60000 + int(secs)*1000 + int(cs.ljust(3,'0'))
                    text = text.strip()
                    # Skip empty lines and pure instrumental markers
                    if text and not _instrumental.match(text):
                        lines.append({"ms": ms, "text": text})
            return lines if lines else None

        def _fetch_syncedlyrics():
            """Returns (plain_text, lrc_lines_or_None)."""
            try:
                import syncedlyrics, re as _re
                # Try plain text first
                plain = syncedlyrics.search(query, plain_only=True)
                if plain and plain.strip():
                    return plain.strip(), None
                # Try synced/LRC — parse timestamps for real-time glow
                synced = syncedlyrics.search(query)
                if synced:
                    lrc_lines = _parse_lrc(synced)
                    if lrc_lines:
                        plain_text = '\n'.join(l['text'] for l in lrc_lines)
                        return plain_text, lrc_lines
                    # No parseable timestamps — strip and return plain
                    clean = _re.sub(r'\[\d{2}:\d{2}[.:]\d{2,3}\]', '', synced)
                    clean = _re.sub(r'\[(?!feat|ft)[^\]]*\]', '', clean)
                    clean = _re.sub(r'\n{3,}', '\n\n', clean.strip())
                    return clean, None
            except Exception as e:
                log.warning(f"syncedlyrics failed: {e}")
            return None, None

        def _fetch_ovh():
            """Fallback: lyrics.ovh (plain text only)."""
            try:
                safe_a = urllib.parse.quote(artist_clean, safe="")
                safe_t = urllib.parse.quote(track_clean,  safe="")
                url    = f"https://api.lyrics.ovh/v1/{safe_a}/{safe_t}"
                req2   = urllib.request.Request(url, headers={"User-Agent": "MAYA/1.0"})
                with urllib.request.urlopen(req2, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
                    return data.get("lyrics") or None
            except Exception:
                return None

        def _find_lyrics():
            text, lrc = _fetch_syncedlyrics()
            if text:
                return text, lrc
            ovh = _fetch_ovh()
            return ovh, None

        # Also get playback position so frontend can offset LRC timestamps
        from spotify_service import get_now_playing_structured as _gnp
        sp_pos = await loop.run_in_executor(None, _gnp)
        progress_ms = sp_pos.get("progress_ms", 0) if sp_pos.get("is_playing") else 0

        lyrics_text, lrc_lines = await loop.run_in_executor(None, _find_lyrics)
        if not lyrics_text:
            return JSONResponse({"found": False, "track": title, "artist": artist,
                                 "reason": "not_found"})
        return JSONResponse({
            "found":       True,
            "track":       title,
            "artist":      artist,
            "lyrics":      lyrics_text,
            "lrc_lines":   lrc_lines,    # [{ms, text}] or null
            "progress_ms": progress_ms,  # current playback position at time of fetch
        })
    except Exception as exc:
        log.error(f"/lyrics error: {exc}")
        return JSONResponse({"found": False, "reason": str(exc)})

# ── /ws  — voice proxy ────────────────────────────────────────────────────────
@app.websocket("/ws")
async def voice_proxy(browser_ws: WebSocket):
    if not pm.origin_allowed(browser_ws.headers.get("origin"), browser_ws.headers.get("host")):
        await browser_ws.close(code=1008)
        return
    await browser_ws.accept()

    dg_key = os.getenv("DEEPGRAM_API_KEY")
    if not dg_key:
        await browser_ws.send_json({"type": "Error", "message": "Voice service is not configured."})
        await browser_ws.close()
        return

    sid = None
    if pm.PUBLIC:
        ip = _client_ip(browser_ws.headers, browser_ws.client.host if browser_ws.client else "?")
        refusal = pm.gate.admit(ip)
        if refusal:
            await browser_ws.send_json({"type": "Limit", "message": refusal})
            await browser_ws.close()
            return
        sid = pm.new_session()
    started = time.monotonic()
    log.info("Browser connected")
    try:
        await _proxy(browser_ws, dg_key, sid)
    finally:
        if pm.PUBLIC:
            pm.gate.release(time.monotonic() - started)
            pm.end_session(sid)


REMINDER_POLL_SECONDS = 5
MAX_RECONNECTS = 3
MAX_CALLS_PER_TURN = 6
RECONNECT_BACKOFF_SECONDS = 1.0


def _due_reminders(sid):
    from reminders import check_reminders
    with pm.session_state(sid):
        return check_reminders()


def _run_in_session(sid, fname, args):
    if pm.blocked(fname):
        return dict(pm.BLOCKED_REPLY)
    with pm.session_state(sid):
        return run_function(fname, args)


async def _proxy(browser_ws: WebSocket, dg_key: str, sid):

    dg_url = "wss://agent.deepgram.com/v1/agent/converse"
    conn = {"ws": None}     # the current Deepgram connection; replaced on reconnect
    history = []            # the conversation so far, replayed to Deepgram after a drop
    stop_event = asyncio.Event()
    # messages MAYA should say unprompted (due reminders). Deepgram
    # rejects an injection while she is thinking or talking, so they
    # wait for her to be idle
    pending_says = []
    idle = [False]
    last_said = [None, 0.0]
    # tool calls made since the user last spoke: an identical call is
    # executed once, and a runaway loop is capped (see MAX_CALLS_PER_TURN)
    turn_calls = {}

    async def connect(resume: bool):
        ws = await websockets.connect(
            dg_url,
            additional_headers={"Authorization": f"Token {dg_key}"},
            # keep-alive pings: a dropped connection is noticed within ~40 s
            # instead of only when the next send fails
            ping_interval=20,
            ping_timeout=20,
            max_size=10 * 1024 * 1024,
        )
        with pm.session_state(sid):
            config = pm.filter_settings(build_settings_config())
        if resume:
            # carry on the same conversation, without greeting again
            config["agent"].pop("greeting", None)
            config["agent"].setdefault("context", {})["messages"] = history[-40:]
        await ws.send(json.dumps(config))
        conn["ws"] = ws
        log.info("Connected to Deepgram Voice Agent" + (" (resumed)" if resume else ""))

    async def session_timer():
        """Public sessions end on time; the page is told why."""
        if not pm.PUBLIC:
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=pm.LIMITS["session_seconds"])
        except asyncio.TimeoutError:
            stop_event.set()
            try:
                await browser_ws.send_json({"type": "Limit", "message": "That's the end of this demo session. Thanks for talking with MAYA."})
                await browser_ws.close()
            except Exception:
                pass
            if conn["ws"] is not None:
                await conn["ws"].close()

    async def browser_to_deepgram():
        """Forward mic audio from browser to Deepgram. Frames that arrive
        while reconnecting are dropped: live audio is not worth replaying."""
        try:
            while not stop_event.is_set():
                data = await browser_ws.receive_bytes()
                ws = conn["ws"]
                if ws is not None:
                    try:
                        await ws.send(data)
                    except Exception:
                        pass  # the reader below notices the drop and reconnects
        except (WebSocketDisconnect, Exception):
            stop_event.set()
            # unblock deepgram_to_browser so the session ends (and
            # its metered slot is released) as soon as the visitor leaves
            if conn["ws"] is not None:
                await conn["ws"].close()

    async def handle(ws, raw):
        if isinstance(raw, bytes):
            # TTS audio: pass straight to browser
            await browser_ws.send_bytes(raw)
            return

        msg = json.loads(raw)
        mtype = msg.get("type", "")

        if mtype == "ConversationText" and msg.get("content"):
            history.append({"type": "History", "role": msg.get("role", "user"), "content": msg["content"]})
            if msg.get("role") == "user":
                turn_calls.clear()

        if mtype in ("UserStartedSpeaking", "AgentThinking", "FunctionCallRequest", "AgentStartedSpeaking"):
            idle[0] = False
        elif mtype == "AgentAudioDone":
            idle[0] = True
            if pending_says:
                asyncio.get_running_loop().call_later(0.8, lambda: asyncio.ensure_future(_say_next()))
        elif mtype in ("InjectionRefused", "Warning") and last_said[0] and time.monotonic() - last_said[1] < 3:
            # she was busy after all: put it back for the next AgentAudioDone
            pending_says.insert(0, last_said[0])
            last_said[0] = None
            idle[0] = False

        if mtype == "FunctionCallRequest":
            # Deepgram sends: {"functions": [{"id": ..., "name": ..., "arguments": "{}"}]}
            for func_call in msg.get("functions", []):
                fname   = func_call.get("name", "")
                func_id = func_call.get("id", "")
                raw_args = func_call.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    args = {}
                log.info(f"Function call: {fname}({args})")

                # Step 1: instantly show a loading card in the browser
                await browser_ws.send_json({
                    "type": "UICardLoading",
                    "function_name": fname,
                })

                # Step 2: execute the function in the thread pool (non-blocking),
                # unless it repeats a call already made for this request
                key = fname + json.dumps(args, sort_keys=True)
                turn_calls[key] = turn_calls.get(key, 0) + 1
                if turn_calls[key] > 1 or sum(turn_calls.values()) > MAX_CALLS_PER_TURN:
                    log.warning(f"Skipped repeated call: {fname}")
                    result = {"result": "Already done for this request; do not call it again. Answer the user now.",
                              "ui_type": "none", "ui_data": {}}
                else:
                    try:
                        loop = asyncio.get_running_loop()
                        result = await loop.run_in_executor(
                            None, _run_in_session, sid, fname, args
                        )
                    except Exception as exc:
                        log.error(f"Function {fname} error: {exc}")
                        result = {"result": str(exc), "ui_type": "none", "ui_data": {}}

                # Step 3: FunctionCallResponse and UICard together, so Deepgram
                # starts speaking as the browser receives the real card
                await asyncio.gather(
                    ws.send(json.dumps({
                        "type": "FunctionCallResponse",
                        "name": fname,
                        "id": func_id,
                        "content": json.dumps(result["result"]),
                    })),
                    browser_ws.send_json({
                        "type": "UICard",
                        "function_name": fname,
                        "ui_type": result.get("ui_type", "none"),
                        "ui_data": result.get("ui_data", {}),
                        "result_text": result["result"],
                    }),
                )
        else:
            # Forward everything else to browser as-is
            await browser_ws.send_json(msg)

    async def deepgram_to_browser():
        """Forward Deepgram messages to the browser, intercepting function
        calls. If the connection to Deepgram drops, reconnect and resume the
        conversation instead of ending the visitor's session."""
        failures = 0
        while not stop_event.is_set():
            ws = conn["ws"]
            try:
                if ws is None:
                    raise ConnectionError("not connected")
                async for raw in ws:
                    if stop_event.is_set():
                        return
                    failures = 0
                    await handle(ws, raw)
                if stop_event.is_set():
                    return
                raise ConnectionError("Deepgram closed the connection")
            except Exception as exc:
                if stop_event.is_set():
                    return
                failures += 1
                conn["ws"] = None
                idle[0] = False
                if failures > MAX_RECONNECTS:
                    log.error(f"Deepgram connection lost for good: {exc}")
                    try:
                        await browser_ws.send_json({"type": "Error", "message": "MAYA lost her connection to the voice service. Please start again."})
                        await browser_ws.close()
                    except Exception:
                        pass
                    stop_event.set()
                    return
                log.warning(f"Deepgram connection lost ({exc}); reconnecting {failures}/{MAX_RECONNECTS}")
                try:
                    await browser_ws.send_json({"type": "Reconnecting"})
                except Exception:
                    pass
                await asyncio.sleep(RECONNECT_BACKOFF_SECONDS * failures)
                try:
                    await connect(resume=True)
                except Exception as exc2:
                    log.warning(f"Reconnect attempt failed: {exc2}")

    async def _say_next():
        """Say the oldest pending message if MAYA is idle; otherwise the
        next AgentAudioDone calls this again."""
        ws = conn["ws"]
        if not pending_says or stop_event.is_set() or not idle[0] or ws is None:
            return
        idle[0] = False
        msg = pending_says.pop(0)
        last_said[0], last_said[1] = msg, time.monotonic()
        await ws.send(json.dumps({"type": "InjectAgentMessage", "message": msg}))

    async def reminder_watcher():
        """A reminder that comes due rings in the page and MAYA
        says it aloud, the same as on the home device."""
        loop = asyncio.get_running_loop()
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=REMINDER_POLL_SECONDS)
                return
            except asyncio.TimeoutError:
                pass
            try:
                due = await loop.run_in_executor(None, _due_reminders, sid)
                for message in due:
                    log.info("Reminder due")
                    await browser_ws.send_json({"type": "ReminderDue", "message": message})
                    spoken = message[:1].lower() + message[1:]
                    pending_says.append(f"Here's your reminder: {spoken}.")
                    await _say_next()
            except Exception as exc:
                log.warning(f"Reminder check failed: {exc}")

    try:
        await connect(resume=False)
        log.info("Settings sent to Deepgram")
        await asyncio.gather(
            browser_to_deepgram(),
            deepgram_to_browser(),
            session_timer(),
            reminder_watcher(),
        )
    except Exception as exc:
        log.error(f"Proxy error: {exc}")
        try:
            # internal detail stays in the log; the visitor gets a plain message
            await browser_ws.send_json({"type": "Error", "message": "MAYA could not reach the voice service. Please try again." if pm.PUBLIC else str(exc)})
        except Exception:
            pass
    finally:
        if conn["ws"] is not None:
            try:
                await conn["ws"].close()
            except Exception:
                pass
        log.info("Browser session ended")


# ── static files ──────────────────────────────────────────────────────────────
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
