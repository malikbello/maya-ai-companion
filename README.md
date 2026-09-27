# MAYA — AI Companion

A voice-first personal AI assistant that listens, thinks, and speaks in real time.
Built on Deepgram's unified Voice Agent API (single WebSocket for STT + LLM + TTS),
with a suite of smart home, health, music, and emergency features callable by voice.

## Run the webapp with Docker

```bash
docker build -t maya-ai-companion .
docker run -p 8000:8000 --env-file .env maya-ai-companion
```

The native voice pipeline (`ai_companion/main.py`) needs direct microphone/speaker
access (and Raspberry Pi GPIO in motion-detection mode), so it's designed to run
natively on the host rather than inside the container — see `SETUP.txt`.

### Public mode

`MAYA_MODE=public` serves the webapp to anonymous visitors safely:

- **Personal integrations are off.** Spotify, Telegram, the motion sensor and the
  emergency SOS flow are removed from the agent's tool list and refused by the
  dispatcher; `/function` and `/lyrics` return 403.
- **Every voice session gets its own throwaway state.** Health logs, reminders and
  names live in a per-session temp directory that is deleted when the call ends.
- **Sessions are metered**, because each one spends speech credits: a length cap,
  per-IP hourly limit, concurrency cap and a daily budget of agent minutes.
- **Hardened HTTP surface:** WebSocket origin check, strict Content-Security-Policy
  (no inline script), HSTS, no CORS, no API docs, non-root container.

| Variable | Default | Meaning |
|---|---|---|
| `DEEPGRAM_API_KEY` | — | Required. Deepgram Voice Agent key. |
| `WEATHER_API_KEY` | — | OpenWeatherMap key for weather cards. |
| `MAYA_MODE` | `personal` | `public` enables everything above. |
| `MAYA_SESSION_SECONDS` | `180` | Length of one voice session. |
| `MAYA_SESSIONS_PER_IP_HOUR` | `4` | Sessions one visitor can start per hour. |
| `MAYA_MAX_CONCURRENT` | `3` | Simultaneous sessions. |
| `MAYA_DAILY_MINUTES` | `60` | Total agent minutes per UTC day. |
| `MAYA_ALLOWED_ORIGINS` | — | Extra origins allowed to open the voice socket. |

```bash
pip install -r webapp/requirements.txt pytest httpx
python -m pytest webapp/tests -q   # public-mode guarantees
```

---

## What MAYA Does — End to End

### 1. Voice Pipeline
| Stage | Technology | Detail |
|---|---|---|
| **Wake** | Always-on microphone | Deepgram Nova-2 listens continuously |
| **STT** | Deepgram Nova-2 | Streaming speech-to-text, low latency |
| **LLM** | OpenAI GPT-4o-mini | Conversational reasoning + function routing |
| **TTS** | Deepgram Aura 2 (Thalia) | Natural-sounding voice response |
| **Transport** | Single WebSocket | `wss://agent.deepgram.com/v1/agent/converse` |

Everything flows through **one** persistent WebSocket. There is no separate STT → LLM → TTS handoff; Deepgram handles the full loop so latency is minimal.

---

### 2. Capability Map

#### Time & Date
- "What time is it?" / "What day is it?"

#### Weather
- "What's the weather?" → current conditions for configured city (default: Lagos)
- "What's the forecast for tomorrow?" → up to 5-day forecast via OpenWeatherMap
- Translates raw numbers into actionable advice ("carry an umbrella", "stay hydrated")

#### Alarms & Reminders
- "Set an alarm for 7 AM" — parsed and stored, fires a chime + voice alert
- "Set a reminder to take my medication in 2 hours" — natural-language time parsing
- "Stop the alarm" / "Dismiss reminder" — voice-cancellable
- Background threads check every 30 seconds and inject audio alerts via the agent

#### Health Tracking
All logged to `health_profile.json`, persisted across sessions.

| Voice command example | Action |
|---|---|
| "I slept 7 hours last night" | `log_sleep` — tracks 7-day rolling average |
| "I drank 3 glasses of water" | `log_water` — tracks daily hydration vs. goal |
| "I'm feeling anxious today" | `log_mood` — sentiment + stress level |
| "I have a headache" | `log_symptom` — symptom log with timestamp |
| "I went for a 30-minute run" | `log_exercise` — type + duration |
| "I took my Metformin" | `log_medication_taken` — medication adherence log |
| "Add Metformin to my medications" | `add_medication` — adds to medication list |
| "I have diabetes" | `add_health_condition` — adds to conditions |
| "How am I doing health-wise?" | `get_health_summary` / `get_wellness_score` |

Proactive daily check-in: MAYA asks how you are each morning if it hasn't heard from you.

#### Health News (no API key required)
- "What's the latest health news?" → headlines from BBC Health + Medical News Today (RSS)
- "Any news about diabetes?" → filters headlines by topic keyword

#### Spotify Music Control
Requires Spotify Premium and configured OAuth credentials.

| Voice command | Function |
|---|---|
| "Play Afrobeats" | `play_spotify` |
| "Play songs by Burna Boy" | `play_spotify_artist` |
| "Pause" / "Resume" | `pause_spotify` / `resume_spotify` |
| "Next song" / "Go back" | `skip_track` / `previous_track` |
| "Set volume to 60" | `set_spotify_volume` |
| "What's playing?" | `get_now_playing` |

#### Emergency SOS
- Highest-priority intent. Triggered by: "emergency", "help me", "SOS", "I'm not okay"
- Sends a Telegram SOS message with your name, timestamp, medical conditions, and medications
- Repeats every 5 minutes until cancelled or someone replies to the Telegram bot
- "Cancel emergency" / "I'm safe" / "All clear" → stops all alerts

#### Telegram Messaging
- "Send a message saying I'll be home late" → `send_telegram_message`
- "Send my health report to Telegram" → formatted health summary sent to configured chat
- "Is Telegram set up?" → `check_telegram_status`

#### Motion Detection (Raspberry Pi / Webcam / Simulation)
Auto-selects backend in priority order: RPi GPIO PIR sensor → OpenCV webcam → Simulation

| Voice command | Action |
|---|---|
| "Start motion monitoring" | Starts background motion detection thread |
| "Stop motion monitoring" | Stops the thread |
| "Motion status" | Reports active/inactive, backend, last trigger time |
| "Set motion cooldown to 60 seconds" | Adjusts minimum time between alerts |

When motion is detected, MAYA speaks aloud: "Hello! I noticed some movement." or "Welcome back" on repeat triggers.

#### Multi-User Support
- Each user gets an isolated profile directory under `ai_companion/users/`
- Separate conversation history, reminders, alarms, and health data per user

---

## Project Structure

```
AI_Companion/
├── ai_companion/               ← All application code lives here
│   ├── run_agent_minimal.py    ← MAIN LAUNCHER (use this)
│   ├── voice_agent_deepgram.py ← Core voice agent, all function registrations
│   ├── brain.py                ← OpenAI GPT-4o-mini interface
│   ├── motion.py               ← Motion detection (GPIO/OpenCV/Simulation)
│   ├── health_analysis.py      ← Health tracking functions
│   ├── health_memory.py        ← Health profile persistence
│   ├── health_news.py          ← RSS health news (BBC, Medical News Today)
│   ├── spotify_service.py      ← Spotify OAuth + playback control
│   ├── telegram_service.py     ← Telegram bot messaging
│   ├── emergency.py            ← SOS alert system
│   ├── weather.py              ← OpenWeatherMap integration
│   ├── reminders.py / alarms.py← Reminder and alarm management
│   ├── user_manager.py         ← Multi-user profile management
│   ├── conversation.py         ← Conversation history buffer
│   ├── .env                    ← API keys (DO NOT COMMIT)
│   ├── health_profile.json     ← Persisted health data
│   ├── users/                  ← Per-user data directory
│   └── models/                 ← Vosk offline speech model
│       └── vosk-model-small-en-us-0.15/
└── cleanenv/                   ← Python virtual environment
    └── Scripts/
        └── python.exe          ← Python interpreter to use
```

---

## Prerequisites

### API Keys Required

| Service | Key Name in `.env` | Where to get it |
|---|---|---|
| Deepgram | `DEEPGRAM_API_KEY` | https://console.deepgram.com |
| OpenAI | `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| OpenWeatherMap | `WEATHER_API_KEY` | https://openweathermap.org/api |
| Telegram Bot | `TELEGRAM_BOT_TOKEN` | Talk to @BotFather on Telegram |
| Telegram Chat ID | `TELEGRAM_CHAT_ID` | Your personal or group chat ID |
| Spotify (optional) | `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` | https://developer.spotify.com/dashboard |

### `.env` file format
Located at `ai_companion/.env`:

```
OPENAI_API_KEY=sk-proj-...
DEEPGRAM_API_KEY=044f60...
WEATHER_API_KEY=4acf84...
TELEGRAM_BOT_TOKEN=877627...
TELEGRAM_CHAT_ID=877180...
SPOTIFY_CLIENT_ID=e305b6...
SPOTIFY_CLIENT_SECRET=76e676...
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

> No inline comments after values — `key=value  # comment` will break loading.

### Hardware
- **Microphone** — any USB or built-in mic (device index set in `voice_agent_deepgram.py` line ~37: `MIC_DEVICE = 5`)
- **Speakers** — any output device
- **Raspberry Pi (optional)** — for real PIR motion sensor on GPIO pin 7 (BCM)

---

## How to Launch

> **Critical:** MAYA must be launched from inside the `ai_companion` directory.
> This ensures the `.env` file and all module imports resolve correctly.

### Step 1 — Open a terminal and navigate to the app directory

```powershell
cd ai_companion
```

### Step 2 — Run using the project virtual environment

```powershell
..\cleanenv\Scripts\python.exe run_agent_minimal.py
```

> **Do NOT use** `python run_agent_minimal.py` or any system Python.
> Always use the full path to `cleanenv\Scripts\python.exe`.

### Expected startup output

```
======================================================================
[AI] AI COMPANION - UNIFIED VOICE AGENT (MINIMAL)
======================================================================
[OK] API keys found
[*] Importing Voice Agent...
[OK] Voice Agent imported
[*] Creating agent with functions...
[OK] Agent created
[*] Starting Voice Agent thread...
======================================================================
[MIC] VOICE AGENT RUNNING - Try speaking!
[MSG] Say: 'What time is it?', 'What's the weather?', 'Set an alarm'
[STOP] Press Ctrl+C to stop
======================================================================
```

### Step 3 — Start talking

Speak naturally. No wake word is required. Examples to try:

```
"What time is it?"
"What's the weather like today?"
"Set an alarm for 8 AM tomorrow"
"I slept 7 hours last night"
"Play some Afrobeats on Spotify"
"What's the latest health news?"
"Start motion monitoring"
"Send a Telegram message saying I'll be late"
```

### Step 4 — Stop

Press `Ctrl+C` in the terminal. MAYA shuts down cleanly.

---

## Troubleshooting

### "Missing API keys" on startup
The `.env` file was not found. Make sure you ran the command from inside `ai_companion/`, not from the project root.

### No audio / microphone silence
The mic device index may be wrong for your machine. Run the device scanner:
```powershell
..\cleanenv\Scripts\python.exe test_devices.py
```
Then update `MIC_DEVICE` at line ~37 in `voice_agent_deepgram.py`.

### Spotify "Invalid client secret"
Check `.env` has no trailing spaces or inline comments after the secret value.

### Motion detection always shows "simulation" backend
This is correct on Windows. The simulation backend is used for testing. On a Raspberry Pi with RPi.GPIO installed, it will automatically switch to the GPIO backend.

### ModuleNotFoundError on launch
You are using the wrong Python. Use the project virtual environment (`cleanenv\Scripts\python.exe`), not the system Python.

---

## Development Notes

- **Virtual environment:** `cleanenv/` at the repo root
- **Python version:** 3.9 for the native pipeline (use `Optional[X]`, not `X | None`); the web app image runs 3.13
- **Logging:** INFO by default; `MAYA_LOG_LEVEL=DEBUG` for more. Library header logging stays off so API keys never reach the logs.
