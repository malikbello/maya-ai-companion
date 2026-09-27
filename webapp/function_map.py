"""
Function Map — bridges browser WebSocket function calls to existing Python handlers.
Returns both the text result (for Deepgram) and structured UI data (for cards).
"""

import os
import re
import sys
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

AI_DIR = Path(__file__).parent.parent / "ai_companion"
sys.path.insert(0, str(AI_DIR))
load_dotenv(AI_DIR / ".env")

# ── existing backend imports (nothing changed in ai_companion/) ───────────────
from command_handlers import (
    handle_time_command, handle_date_command, handle_weather_command,
    handle_check_alarms, handle_set_alarm_direct,
    handle_check_reminders, handle_set_reminder_direct,
    handle_set_name, handle_set_location,
)
from user_manager import get_current_user
from health_memory import load_profile, get_log_entries
from health_analysis import (
    log_sleep, log_water, log_mood, log_symptom, log_exercise,
    log_medication_taken, add_medication, add_health_condition,
    set_health_emergency_contact, get_health_summary, get_wellness_score,
)
from health_news import get_health_news, get_health_news_by_topic
from emergency import trigger_emergency, cancel_emergency, set_doctor_contact
from telegram_service import (
    send_voice_message as _tg_send,
    message_doctor as _tg_doctor,
    DOCTOR_NAME as _DOCTOR_NAME,
    send_health_report_telegram as _tg_report,
    check_telegram_status as _tg_status,
)
from spotify_service import (
    play_music, play_artist_music, pause_music, resume_music,
    next_track, previous_track, set_volume, get_now_playing, get_now_playing_structured, close_spotify,
)
from motion import (
    start_motion_monitoring, stop_motion_monitoring,
    get_motion_status, set_motion_cooldown,
)
from weather import get_weather_forecast as _forecast

_WEATHER_KEY = os.getenv("WEATHER_API_KEY")


def _forecast_raw(city: str) -> dict:
    """Structured 5-day forecast data — one entry per calendar day."""
    from collections import defaultdict
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": _WEATHER_KEY, "units": "metric", "cnt": 40},
            timeout=6,
        )
        if r.status_code != 200:
            return {"city": city, "days": []}
        data = r.json()
    except Exception:
        return {"city": city, "days": []}

    from datetime import timedelta
    today_str = datetime.now().strftime("%Y-%m-%d")
    by_date = defaultdict(list)
    for item in data["list"]:
        by_date[item["dt_txt"][:10]].append(item)

    days = []
    for date_str, items in sorted(by_date.items()):
        if len(days) >= 5:
            break
        dt      = datetime.strptime(date_str, "%Y-%m-%d")
        noon    = next((i for i in items if "12:00:00" in i["dt_txt"]), items[len(items)//2])
        t_max   = round(max(i["main"]["temp_max"] for i in items), 1)
        t_min   = round(min(i["main"]["temp_min"] for i in items), 1)
        rain_ch = int(max(i.get("pop", 0) for i in items) * 100)
        days.append({
            "date":        date_str,
            "day_name":    dt.strftime("%A"),
            "day_short":   dt.strftime("%a").upper(),
            "is_today":    date_str == today_str,
            "icon":        noon["weather"][0]["icon"],
            "condition":   noon["weather"][0]["main"],
            "description": noon["weather"][0]["description"],
            "temp_max":    t_max,
            "temp_min":    t_min,
            "temp_noon":   round(noon["main"]["temp"], 1),
            "humidity":    noon["main"]["humidity"],
            "wind_speed":  round(noon["wind"]["speed"], 1),
            "rain_chance": rain_ch,
        })

    country = data.get("city", {}).get("country", "")
    return {"city": city, "country": country, "days": days}


def _forecast_summary(fc: dict) -> str:
    """One line per day, in words the model can reason over and speak."""
    lines = [f"{len(fc['days'])}-day forecast for {fc['city']} (the free forecast covers five days):"]
    for d in fc["days"]:
        label = "Today" if d["is_today"] else f"{d['day_name']} {d['date']}"
        lines.append(
            f"{label}: {d['description']}, {round(d['temp_min'])} to {round(d['temp_max'])} degrees Celsius, "
            f"{d['rain_chance']}% chance of rain, wind {d['wind_speed']} m/s."
        )
    return "\n".join(lines)


def _medication_info(name: str) -> dict:
    """Fetch structured medication info from OpenFDA drug label API (free, no key)."""
    def _clean(lst, max_chars=420):
        if not lst:
            return None
        text = lst[0] if isinstance(lst, list) else str(lst)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars] + ('…' if len(text) > max_chars else '')

    def _steps(raw, max_steps=5):
        if not raw:
            return []
        parts = re.split(r'(?<=[.;])\s+', raw)
        return [p.strip().rstrip('.;') for p in parts if len(p.strip()) > 12][:max_steps]

    # SAFETY: block obviously harmful/illicit queries
    _BLOCKED = {'heroin','cocaine','meth','methamphetamine','crack','fentanyl','lsd',
                'mdma','ecstasy','pcp','ketamine recreational','crystal meth'}
    if any(w in name.lower() for w in _BLOCKED):
        return {"name": name, "blocked": True, "found": False}

    base = "https://api.fda.gov/drug/label.json"
    drug = None
    for query in [f'openfda.brand_name:"{name}"', f'openfda.generic_name:"{name}"', name]:
        try:
            r = requests.get(base, params={"search": query, "limit": 1}, timeout=7)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    drug = results[0]
                    break
        except Exception:
            pass

    if not drug:
        return {"name": name.title(), "found": False}

    openfda = drug.get("openfda", {})
    brand   = openfda.get("brand_name", [])
    generic = openfda.get("generic_name", [])
    route   = (openfda.get("route", ["oral"])[0]).lower() if openfda.get("route") else "oral"

    raw_dosage = _clean(drug.get("dosage_and_administration"), 800)
    return {
        "name":         (brand[0] if brand else name).title(),
        "generic_name": (generic[0] if generic else "").title(),
        "route":        route,
        "found":        True,
        "indications":  _clean(drug.get("indications_and_usage")),
        "steps":        _steps(raw_dosage),
        "dosage_raw":   raw_dosage,
        "warnings":     _clean(drug.get("warnings") or drug.get("warnings_and_cautions")),
        "side_effects": _clean(drug.get("adverse_reactions"), 280),
        "do_not":       _clean(drug.get("contraindications"), 280),
    }


def _enrich_alarms(alarms: list) -> list:
    """Add day-aware labels to each alarm so the card can show Today / Tomorrow."""
    now = datetime.now()
    result = []
    for a in alarms:
        alarm = dict(a)
        t = a.get("time", "")
        try:
            h, m = map(int, t.split(":"))
            alarm_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if alarm_today > now:
                alarm["when"]         = "Today"
                alarm["when_label"]   = alarm_today.strftime("Today at %I:%M %p")
                alarm["is_today"]     = True
                alarm["minutes_away"] = int((alarm_today - now).total_seconds() / 60)
            else:
                nxt = alarm_today + timedelta(days=1)
                alarm["when"]         = "Tomorrow"
                alarm["when_label"]   = nxt.strftime("Tomorrow at %I:%M %p")
                alarm["is_today"]     = False
                alarm["minutes_away"] = int((nxt - now).total_seconds() / 60)
            alarm["time_12h"] = alarm_today.strftime("%I:%M %p").lstrip("0")
        except Exception:
            alarm["when"]         = ""
            alarm["when_label"]   = t
            alarm["time_12h"]     = t
            alarm["is_today"]     = False
            alarm["minutes_away"] = None
        result.append(alarm)
    return sorted(result, key=lambda x: (0 if x.get("is_today") else 1, x.get("time", "")))


def _enrich_reminders(reminders: list) -> list:
    """Add when_label / is_past to reminders for display."""
    now        = datetime.now()
    today_str  = now.strftime("%Y-%m-%d")
    tmrw_str   = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    result     = []
    for r in reminders:
        rem = dict(r)
        dt_str = r.get("datetime", "")
        try:
            dt = datetime.strptime(dt_str[:16], "%Y-%m-%d %H:%M")  # stored with or without seconds
            d  = dt.strftime("%Y-%m-%d")
            if d == today_str:
                rem["when"]       = "Today"
                rem["when_label"] = dt.strftime("Today at %I:%M %p").replace(" 0", " ")
            elif d == tmrw_str:
                rem["when"]       = "Tomorrow"
                rem["when_label"] = dt.strftime("Tomorrow at %I:%M %p").replace(" 0", " ")
            else:
                rem["when"]       = dt.strftime("%A")
                rem["when_label"] = dt.strftime("%A, %b %d at %I:%M %p").replace(" 0", " ")
            rem["is_past"]      = dt < now
            rem["time_display"] = dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            rem["when"]         = ""
            rem["when_label"]   = dt_str
            rem["is_past"]      = False
            rem["time_display"] = dt_str
        result.append(rem)
    return sorted(result, key=lambda x: (1 if x.get("is_past") else 0, x.get("datetime", "")))


def _weather_raw(city: str) -> dict:
    """Raw OpenWeather API call for UI card data."""
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": _WEATHER_KEY, "units": "metric"},
            timeout=5,
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "city": city,
                "temp": round(d["main"]["temp"]),
                "feels_like": round(d["main"]["feels_like"]),
                "humidity": d["main"]["humidity"],
                "description": d["weather"][0]["description"].capitalize(),
                "icon": d["weather"][0]["icon"],
                "condition": d["weather"][0]["main"],
                "wind_speed": round(d["wind"]["speed"], 1),
                "temp_min": round(d["main"]["temp_min"]),
                "temp_max": round(d["main"]["temp_max"]),
            }
    except Exception:
        pass
    return {}


def _health_ui() -> dict:
    """Build health card data from today's health profile."""
    try:
        profile = load_profile()
        sleep_log = get_log_entries("sleep_log", days=1)
        mood_log  = get_log_entries("mood_log",  days=1)
        ex_log    = get_log_entries("exercise_log", days=1)
        return {
            "sleep_hours":  sleep_log[-1]["hours"]            if sleep_log else None,
            "sleep_quality": sleep_log[-1].get("quality")    if sleep_log else None,
            "water_glasses": profile.get("hydration_today", 0),
            "water_goal":    profile.get("hydration_goal", 8),
            "mood":          mood_log[-1].get("mood")         if mood_log  else None,
            "mood_score":    mood_log[-1].get("score")        if mood_log  else None,
            "exercise_mins": sum(e.get("duration_minutes", 0) for e in ex_log),
            "meds_taken":    profile.get("medications_taken_today", []),
        }
    except Exception:
        return {}


# ── dispatch ──────────────────────────────────────────────────────────────────
def run_function(name: str, args: dict) -> dict:
    """Execute a function and return {result, ui_type, ui_data}."""
    user = get_current_user()
    city = user.data.get("location", "Lagos")

    # helper so every return has the same shape
    def resp(result, ui_type="none", ui_data=None):
        return {"result": result, "ui_type": ui_type, "ui_data": ui_data or {}}

    # ── time / date ────────────────────────────────────────────────
    if name == "get_time":
        now = datetime.now()
        return resp(handle_time_command(""), "time", {
            "time":     now.strftime("%I:%M %p"),
            "hours24":  now.hour,
            "minutes":  now.minute,
            "seconds":  now.second,
        })

    if name == "get_date":
        now = datetime.now()
        return resp(handle_date_command(""), "date", {
            "weekday": now.strftime("%A"),
            "date":    now.strftime("%B %d, %Y"),
            "month":   now.strftime("%B"),
            "day":     now.day,
            "year":    now.year,
        })

    # ── weather ───────────────────────────────────────────────────
    if name == "get_weather":
        result = handle_weather_command("")
        return resp(result, "weather", _weather_raw(city))

    if name == "get_weather_forecast":
        # The model gets every day with its rain chance, so it can compare
        # days ("which day this week is dry?"), not just read out one.
        where      = (args.get("city") or city).strip()
        days_ahead = int(args.get("days_ahead", 5))
        structured = _forecast_raw(where)
        structured["requested_days"] = days_ahead
        if not structured["days"]:
            return resp(_forecast(where, days_ahead), "forecast", structured)
        return resp(_forecast_summary(structured), "forecast", structured)

    # ── alarms ────────────────────────────────────────────────────
    if name == "check_alarms":
        result = handle_check_alarms("")
        return resp(result, "alarms", {"alarms": _enrich_alarms(user.get_alarms())})

    if name == "set_alarm":
        result = handle_set_alarm_direct(args.get("time", ""), args.get("label", ""))
        return resp(result, "alarms", {"alarms": _enrich_alarms(user.get_alarms()), "new": args})

    if name == "stop_alarm":
        return resp("Alarm stopped.", "alarm_stopped", {})

    # ── reminders ─────────────────────────────────────────────────
    if name == "check_reminders":
        result = handle_check_reminders("")
        return resp(result, "reminders", {"reminders": _enrich_reminders(user.get_reminders())})

    if name == "set_reminder":
        result = handle_set_reminder_direct(args.get("task", ""), args.get("time", ""))
        return resp(result, "reminder_set", {"task": args.get("task"), "time": args.get("time")})

    if name == "stop_reminder":
        return resp("Reminder dismissed.", "reminder_stopped", {})

    # ── health logging ────────────────────────────────────────────
    if name == "log_sleep":
        result = log_sleep(args.get("hours", 7), args.get("quality", "fair"))
        profile = load_profile()
        sl = get_log_entries("sleep_log", days=7)
        avg = round(sum(e["hours"] for e in sl) / len(sl), 1) if sl else args.get("hours")
        return resp(result, "health_log", {
            "type": "sleep", "hours": args.get("hours"),
            "quality": args.get("quality", "fair"), "avg_7d": avg,
        })

    if name == "log_water":
        result = log_water(args.get("glasses", 1))
        profile = load_profile()
        return resp(result, "health_log", {
            "type": "water",
            "glasses": profile.get("hydration_today", 0),
            "goal": profile.get("hydration_goal", 8),
        })

    if name == "log_mood":
        result = log_mood(args.get("mood", ""), args.get("score"))
        return resp(result, "health_log", {
            "type": "mood", "mood": args.get("mood"), "score": args.get("score"),
        })

    if name == "log_symptom":
        result = log_symptom(args.get("symptom", ""), args.get("severity", 5))
        return resp(result, "health_log", {
            "type": "symptom", "symptom": args.get("symptom"),
            "severity": args.get("severity", 5),
        })

    if name == "log_exercise":
        result = log_exercise(args.get("activity", ""), args.get("duration_minutes", 0))
        return resp(result, "health_log", {
            "type": "exercise",
            "activity": args.get("activity"),
            "minutes": args.get("duration_minutes"),
        })

    if name == "log_medication_taken":
        result = log_medication_taken(args.get("name", ""))
        return resp(result, "health_log", {"type": "medication", "name": args.get("name")})

    if name == "add_medication":
        result = add_medication(args.get("name", ""), args.get("dosage", ""), args.get("times", "morning"))
        return resp(result)

    if name == "add_health_condition":
        result = add_health_condition(args.get("condition", ""))
        return resp(result)

    if name == "set_health_emergency_contact":
        result = set_health_emergency_contact(args.get("phone_number", ""))
        return resp(result)

    # ── health summary / wellness ─────────────────────────────────
    if name == "get_health_summary":
        result = get_health_summary()
        return resp(result, "health_summary", _health_ui())

    if name == "get_wellness_score":
        result = get_wellness_score()
        m = re.search(r"(\d+)", result)
        score = int(m.group(1)) if m else 0
        return resp(result, "wellness_score", {"score": score})

    # ── health news ───────────────────────────────────────────────
    if name == "get_health_news":
        result = get_health_news(topic=args.get("topic"), count=args.get("count", 3))
        return resp(result, "news", {"text": result, "topic": args.get("topic", "Health")})

    if name == "get_health_news_by_topic":
        result = get_health_news_by_topic(args.get("topic", ""))
        return resp(result, "news", {"text": result, "topic": args.get("topic", "Health")})

    if name == "get_medication_info":
        med_name = args.get("medication_name", "")
        data = _medication_info(med_name)
        if data.get("blocked"):
            result = f"I'm not able to provide instructions for {med_name}. I can only help with legitimate prescription or over-the-counter medications."
            return resp(result, "none", {})
        if not data.get("found"):
            result = f"I couldn't find official FDA data for {med_name}, but I'll share general guidance. Please consult your pharmacist or doctor for personalised advice."
            return resp(result, "medication", {"name": med_name.title(), "found": False})
        result = (
            f"{data['name']}"
            + (f" ({data['generic_name']})" if data.get('generic_name') and data['generic_name'] != data['name'] else "")
            + ". "
            + (data.get("dosage_raw") or "Refer to the package insert for dosage details.")
        )
        return resp(result, "medication", data)

    # ── emergency ─────────────────────────────────────────────────
    if name == "trigger_emergency":
        result = trigger_emergency()
        return resp(result, "emergency", {"active": True})

    if name == "cancel_emergency":
        result = cancel_emergency()
        return resp(result, "emergency", {"active": False})

    if name == "set_doctor_contact":
        result = set_doctor_contact(args.get("number", ""))
        return resp(result)

    # ── telegram ──────────────────────────────────────────────────
    if name == "send_telegram_message":
        result = _tg_send(args.get("text", ""))
        return resp(result, "telegram", {"message": args.get("text"), "sent": result.startswith("Done")})

    if name == "message_doctor":
        out = _tg_doctor(args.get("text", ""), user.get_name() if user else "")
        return resp(out["result"], "telegram", {"message": args.get("text"), "sent": out["sent"], "to": _DOCTOR_NAME})

    if name == "send_health_report_telegram":
        result = _tg_report()
        return resp(result, "telegram", {"type": "health_report"})

    if name == "check_telegram_status":
        result = _tg_status()
        return resp(result)

    # ── spotify ───────────────────────────────────────────────────
    if name == "play_spotify":
        result = play_music(args.get("query", ""), args.get("device", None))
        # Wait for Spotify to actually switch: reading now-playing straight
        # away returns the previous track, which MAYA then announced.
        wanted = result[len("Now playing "):].split(" by ")[0] if result.startswith("Now playing ") else ""
        sp_info = {}
        for _ in range(8):
            time.sleep(0.5)
            sp_info = get_now_playing_structured()
            if sp_info.get("is_playing") and (not wanted or sp_info.get("track") == wanted):
                break
        else:
            if wanted:
                result = (f"Spotify accepted the request for {wanted} but hasn't started playing it. "
                          "The Spotify app may need a press of play once before it takes remote commands.")
        actual_track  = sp_info.get("track",  "") if sp_info.get("is_playing") else ""
        actual_artist = sp_info.get("artist", "") if sp_info.get("is_playing") else ""
        return resp(result, "spotify", {
            "action": "play",
            "query":  args.get("query"),
            "text":   result,
            "track":  actual_track  or args.get("query", ""),
            "artist": actual_artist,
        })

    if name == "play_spotify_artist":
        result = play_artist_music(args.get("artist", ""), args.get("device", None))
        time.sleep(0.5)
        sp_info = get_now_playing_structured()
        actual_track  = sp_info.get("track",  "") if sp_info.get("is_playing") else ""
        actual_artist = sp_info.get("artist", "") if sp_info.get("is_playing") else ""
        return resp(result, "spotify", {
            "action": "play",
            "query":  args.get("artist"),
            "text":   result,
            "track":  actual_track  or args.get("artist", ""),
            "artist": actual_artist or args.get("artist", ""),
        })

    if name == "pause_spotify":
        return resp(pause_music(), "spotify", {"action": "pause"})

    if name == "resume_spotify":
        result = resume_music()
        time.sleep(0.5)
        sp_info = get_now_playing_structured()
        actual_track  = sp_info.get("track",  "") if sp_info.get("is_playing") else ""
        actual_artist = sp_info.get("artist", "") if sp_info.get("is_playing") else ""
        return resp(result, "spotify", {
            "action": "resume",
            "track":  actual_track,
            "artist": actual_artist,
        })

    if name == "close_spotify":
        return resp(close_spotify(), "spotify", {"action": "close"})

    if name == "skip_track":
        result = next_track()
        time.sleep(0.8)
        sp_info = get_now_playing_structured()
        actual_track  = sp_info.get("track",  "") if sp_info.get("is_playing") else ""
        actual_artist = sp_info.get("artist", "") if sp_info.get("is_playing") else ""
        return resp(result, "spotify", {
            "action": "next",
            "track":  actual_track,
            "artist": actual_artist,
        })

    if name == "previous_track":
        result = previous_track()
        time.sleep(0.8)
        sp_info = get_now_playing_structured()
        actual_track  = sp_info.get("track",  "") if sp_info.get("is_playing") else ""
        actual_artist = sp_info.get("artist", "") if sp_info.get("is_playing") else ""
        return resp(result, "spotify", {
            "action": "previous",
            "track":  actual_track,
            "artist": actual_artist,
        })

    if name == "set_spotify_volume":
        result = set_volume(int(args.get("percent", 50)))
        return resp(result, "spotify", {"action": "volume", "percent": args.get("percent")})

    if name == "get_now_playing":
        result  = get_now_playing()
        sp_info = get_now_playing_structured()
        return resp(result, "spotify", {
            "action": "now_playing",
            "text":   result,
            "track":  sp_info.get("track",  "") if sp_info.get("is_playing") else "",
            "artist": sp_info.get("artist", "") if sp_info.get("is_playing") else "",
        })

    # ── motion ────────────────────────────────────────────────────
    if name == "start_motion_monitoring":
        return resp(start_motion_monitoring(), "motion", {"active": True})

    if name == "stop_motion_monitoring":
        return resp(stop_motion_monitoring(), "motion", {"active": False})

    if name == "get_motion_status":
        result = get_motion_status()
        return resp(result, "motion", {"text": result, "active": "running" in result.lower()})

    if name == "set_motion_cooldown":
        result = set_motion_cooldown(int(args.get("seconds", 30)))
        return resp(result, "motion", {"cooldown": args.get("seconds")})

    # ── profile ───────────────────────────────────────────────────
    if name == "set_name":
        new_name = args.get("name", "").strip().title()
        result = handle_set_name(new_name)
        # Collect name history for the card
        user2 = get_current_user()
        history = user2.data.get("name_history", [])
        return resp(result, "profile_name", {
            "current_name": user2.get_name(),
            "name_history": history,
        })

    if name == "set_location":
        result = handle_set_location(args.get("city", ""))
        return resp(result)

    # ── fallback ──────────────────────────────────────────────────
    return {"result": f"Unknown function: {name}", "ui_type": "none", "ui_data": {}}


# ── Deepgram Settings payload ─────────────────────────────────────────────────
# Nova-3 keyterm prompting: without it, Nigerian names and places are
# misheard ("Malik" -> "Movik", "Ibadan" -> "Ibotta") and tools get wrong input.
# Keep this list short: every keyterm is also a false-positive risk
# ("I've taken it" was heard as "Ikeja", then "Akure", with longer lists).
_NIGERIAN_PLACES = ["Lagos", "Abuja", "Ibadan", "Kano", "Port Harcourt", "Enugu", "Benin City", "Kaduna"]
_MEDICINES = ["amlodipine", "metformin", "lisinopril", "losartan", "paracetamol", "ibuprofen", "artemether", "lumefantrine", "insulin"]


def _keyterms(user) -> list:
    terms = ["MAYA"] + _NIGERIAN_PLACES + _MEDICINES
    name = user.get_name() if user else ""
    if name and name not in ("User", ""):
        terms.append(name)
    return terms[:100]


def _known_user(user) -> str:
    """What MAYA already knows, so she doesn't ask for it again."""
    if not user:
        return ""
    facts = []
    name = user.get_name()
    if name and name not in ("User", ""):
        facts.append(f"The user's name is {name}.")
    city = user.data.get("location")
    if city and city not in ("Not set", ""):
        facts.append(f"The user lives in {city}; use it for weather and forecasts unless they name another place.")
    return (" KNOWN ABOUT THE USER: " + " ".join(facts)) if facts else ""


def build_settings_config() -> dict:
    """Build the full Deepgram Voice Agent Settings payload."""
    user = get_current_user()
    name = user.get_name() if user else "there"
    greeting = (
        f"Hello{', ' + name if name and name not in ('User','') else ''}! "
        "I'm MAYA, your AI companion. How can I help you today?"
    )

    SYSTEM_PROMPT = (
        "You are MAYA, a warm, intelligent AI companion. "
        "CRITICAL SPEECH RULES — follow these at all times: "
        "1. NEVER use markdown formatting of any kind. No asterisks, dashes for lists, pound signs, or numbered lists. TTS speaks every character literally. Use only plain natural sentences. "
        "2. Be concise and warm. Give short friendly answers like a trusted companion — not a written document. "
        "3. Address the user by their first name whenever you know it. "
        "4. ONLY call set_name when the user is explicitly introducing themselves or asking to update their name — e.g. 'my name is', 'I'm called', 'call me', 'please save my name as', 'change my name to'. Do NOT call set_name just because a name is mentioned in conversation, in a story, about another person, or in any other context. Call set_location ONLY when the user says where they live or that they have moved (e.g. 'I live in', 'I've moved to'); a city they are visiting, planning a trip to or asking about is NOT their location, so never overwrite it for that. "
        "5. For weather questions call get_weather for today, get_weather_forecast for future days. Never guess. Summarise forecasts in two or three short sentences (the overall pattern and anything notable), never day by day; the card shows the details. When asked to pick a day (for a trip, an event, laundry), compare the days' rain chances and recommend the best one in a sentence or two. "
        "6. For time call get_time; for date call get_date. "
        "7. NEVER say filler phrases before calling a function. No 'Let me check', 'Sure', 'Give me a second'. Call silently then speak the answer. "
        "8. Health tracking: log_sleep when user mentions sleep, log_water for water intake, log_mood for mood, log_symptom for symptoms, log_exercise for physical activity, log_medication_taken when they take meds. "
        "9. When asked for health summary or wellness score call get_health_summary or get_wellness_score. "
        "10. EMERGENCY: ONLY call trigger_emergency when the user is CLEARLY in distress and is explicitly asking for emergency help — e.g. 'call emergency', 'SOS', 'send help', 'I need emergency help', 'medical emergency', 'I can't breathe', 'I'm having a heart attack'. Do NOT trigger on casual use of the word 'emergency' in normal conversation (e.g. 'it's not an emergency', 'emergency meeting', 'emergency contact', 'in case of emergency'). If you are unsure, ask: 'Are you okay? Do you need me to call for help?' before triggering. "
        "11. CANCEL EMERGENCY: call cancel_emergency if the user says any of: 'cancel emergency', 'stop emergency', 'cancel SOS', 'stop SOS', 'all clear', 'I am safe', 'I'm safe', 'false alarm', 'never mind', 'abort', 'stop the alarm', 'silence alarm', 'I am fine', 'everything is fine', 'it was a mistake', 'stop it'. "
        "12. SPOTIFY MUSIC CONTROL: call play_spotify to play music by name or genre, play_spotify_artist for a specific artist. If the user says 'on my phone' or 'on my PC/laptop/computer', pass device='phone' or device='pc' to target that device. If the user says stop music, pause music, mute, quiet, silence — call pause_spotify IMMEDIATELY. If the user says close Spotify or quit Spotify — call close_spotify. Call resume_spotify to continue, skip_track for next song, previous_track for the previous song, set_spotify_volume for volume, get_now_playing to check the current track. Never guess — always call the function. "
        "13. TELEGRAM: message_doctor when the user wants to tell or ask their doctor something; read the message back in one short sentence after sending. send_telegram_message to send a message, send_health_report_telegram for health report, check_telegram_status to verify setup. "
        "14. HEALTH NEWS: get_health_news for general news, get_health_news_by_topic for specific topics. "
        "15. MOTION SENSOR: start_motion_monitoring to enable, stop_motion_monitoring to disable, get_motion_status for status, set_motion_cooldown to adjust cooldown. "
        "16. REMINDERS: if the user asks for a reminder but does NOT say what it's for, ask 'What would you like to be reminded about?' first. "
        "17. When listing items use flowing sentences, never bullet points. "
        "18. For weather results give friendly advice \u2014 tell them what to wear or bring, not just numbers. "
        "19. MEDICATION INSTRUCTIONS: When the user asks how to take a medication, what dose to take, or wants to learn about a legitimate prescription or over-the-counter medicine, call get_medication_info immediately. "
        "NEVER provide instructions for illegal drugs, recreational substances, controlled drugs used non-medically, or anything harmful. If asked about such substances, decline politely and offer to help with legitimate health needs instead. "
        "Speak the key instructions naturally after the function returns, then let the visual card guide the user."
    )

    functions = [
        {"name": "get_time",        "description": "Get the current time",                                 "parameters": {"type": "object", "properties": {}}},
        {"name": "get_date",        "description": "Get today's date",                                    "parameters": {"type": "object", "properties": {}}},
        {"name": "get_weather",     "description": "Get current weather for user's location",             "parameters": {"type": "object", "properties": {}}},
        {"name": "get_weather_forecast", "description": "Get the day-by-day forecast (up to five days) with rain chance, for the user's city or another one",
         "parameters": {"type": "object", "properties": {"days_ahead": {"type": "integer", "description": "1=tomorrow up to 5"}, "city": {"type": "string", "description": "Only if the user names a different city, e.g. a trip destination"}}}},
        {"name": "check_alarms",    "description": "Check all set alarms",                                "parameters": {"type": "object", "properties": {}}},
        {"name": "set_alarm",       "description": "Set a new alarm",
         "parameters": {"type": "object", "properties": {"time": {"type": "string"}, "label": {"type": "string"}}, "required": ["time"]}},
        {"name": "stop_alarm",      "description": "Silence an alarm that is ringing right now. Not for music or anything else.",                      "parameters": {"type": "object", "properties": {}}},
        {"name": "check_reminders", "description": "Check all set reminders",                             "parameters": {"type": "object", "properties": {}}},
        {"name": "set_reminder",    "description": "Set a new reminder",
         "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "time": {"type": "string"}}, "required": ["task"]}},
        {"name": "stop_reminder",   "description": "Dismiss a reminder that is ringing right now. Not for music or anything else.",                          "parameters": {"type": "object", "properties": {}}},
        {"name": "log_sleep",       "description": "Log hours of sleep",
         "parameters": {"type": "object", "properties": {"hours": {"type": "number"}, "quality": {"type": "string"}}, "required": ["hours"]}},
        {"name": "log_water",       "description": "Log glasses of water",
         "parameters": {"type": "object", "properties": {"glasses": {"type": "integer"}}, "required": ["glasses"]}},
        {"name": "log_mood",        "description": "Log current mood",
         "parameters": {"type": "object", "properties": {"mood": {"type": "string"}, "score": {"type": "integer"}}, "required": ["mood"]}},
        {"name": "log_symptom",     "description": "Log a health symptom",
         "parameters": {"type": "object", "properties": {"symptom": {"type": "string"}, "severity": {"type": "integer"}}, "required": ["symptom"]}},
        {"name": "log_exercise",    "description": "Log physical activity",
         "parameters": {"type": "object", "properties": {"activity": {"type": "string"}, "duration_minutes": {"type": "integer"}}, "required": ["activity", "duration_minutes"]}},
        {"name": "log_medication_taken", "description": "Mark medication as taken",
         "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "add_medication",  "description": "Add medication to health profile",
         "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "dosage": {"type": "string"}, "times": {"type": "string"}}, "required": ["name"]}},
        {"name": "add_health_condition", "description": "Add a medical condition to profile",
         "parameters": {"type": "object", "properties": {"condition": {"type": "string"}}, "required": ["condition"]}},
        {"name": "set_health_emergency_contact", "description": "Save emergency contact phone",
         "parameters": {"type": "object", "properties": {"phone_number": {"type": "string"}}, "required": ["phone_number"]}},
        {"name": "get_health_summary",   "description": "Get full spoken health summary",                "parameters": {"type": "object", "properties": {}}},
        {"name": "get_wellness_score",   "description": "Get wellness score 0-100",                      "parameters": {"type": "object", "properties": {}}},
        {"name": "get_health_news",      "description": "Fetch latest health news headlines",
         "parameters": {"type": "object", "properties": {"topic": {"type": "string"}, "count": {"type": "integer"}}}},
        {"name": "get_health_news_by_topic", "description": "Search health news by topic",
         "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
        {"name": "get_medication_info", "description": "Get official instructions on how to take a legitimate OTC or prescription medication: dosage, steps, warnings. Do NOT use for illegal drugs or harmful substances.",
         "parameters": {"type": "object", "properties": {"medication_name": {"type": "string", "description": "Brand or generic name of the medication"}}, "required": ["medication_name"]}},
        {"name": "trigger_emergency",    "description": "Trigger emergency SOS alert",                   "parameters": {"type": "object", "properties": {}}},
        {"name": "cancel_emergency",     "description": "Cancel active emergency alert",                 "parameters": {"type": "object", "properties": {}}},
        {"name": "set_doctor_contact",   "description": "Save doctor phone number",
         "parameters": {"type": "object", "properties": {"number": {"type": "string"}}, "required": ["number"]}},
        {"name": "message_doctor", "description": "Send a message to the user's doctor on Telegram. Write the message in the first person, as the user, clearly and politely.",
         "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "The message for the doctor"}}, "required": ["text"]}},
        {"name": "send_telegram_message", "description": "Send Telegram message",
         "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
        {"name": "send_health_report_telegram", "description": "Send weekly health report via Telegram", "parameters": {"type": "object", "properties": {}}},
        {"name": "check_telegram_status",       "description": "Check Telegram bot status",             "parameters": {"type": "object", "properties": {}}},
        {"name": "play_spotify",         "description": "Play a song or playlist on Spotify",
         "parameters": {"type": "object", "properties": {
             "query":  {"type": "string", "description": "Song, album, or playlist name"},
             "device": {"type": "string", "description": "Optional: 'phone' or 'pc' to target a specific device"}
         }, "required": ["query"]}},
        {"name": "play_spotify_artist",  "description": "Play music by an artist on Spotify",
         "parameters": {"type": "object", "properties": {
             "artist": {"type": "string"},
             "device": {"type": "string", "description": "Optional: 'phone' or 'pc'"}
         }, "required": ["artist"]}},
        {"name": "pause_spotify",        "description": "Pause Spotify",                                 "parameters": {"type": "object", "properties": {}}},
        {"name": "resume_spotify",       "description": "Resume Spotify",                                "parameters": {"type": "object", "properties": {}}},
        {"name": "close_spotify",        "description": "Pause playback and close/quit the Spotify app", "parameters": {"type": "object", "properties": {}}},
        {"name": "skip_track",           "description": "Skip to next Spotify track",                    "parameters": {"type": "object", "properties": {}}},
        {"name": "previous_track",       "description": "Go to previous Spotify track",                  "parameters": {"type": "object", "properties": {}}},
        {"name": "set_spotify_volume",   "description": "Set Spotify volume 0-100",
         "parameters": {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]}},
        {"name": "get_now_playing",      "description": "Get currently playing Spotify track",           "parameters": {"type": "object", "properties": {}}},
        {"name": "start_motion_monitoring", "description": "Start motion sensor monitoring",             "parameters": {"type": "object", "properties": {}}},
        {"name": "stop_motion_monitoring",  "description": "Stop motion sensor monitoring",              "parameters": {"type": "object", "properties": {}}},
        {"name": "get_motion_status",       "description": "Get motion sensor status",                   "parameters": {"type": "object", "properties": {}}},
        {"name": "set_motion_cooldown",     "description": "Set motion alert cooldown seconds",
         "parameters": {"type": "object", "properties": {"seconds": {"type": "integer"}}, "required": ["seconds"]}},
        {"name": "set_name",     "description": "Save user's name",
         "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "set_location", "description": "Save user's city/location",
         "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    ]

    return {
        "type": "Settings",
        "audio": {
            "input":  {"encoding": "linear16", "sample_rate": 16000},
            "output": {"encoding": "linear16", "sample_rate": 24000},
        },
        "agent": {
            "language": "en",
            "context": {"messages": []},
            "listen": {"provider": {"type": "deepgram", "model": "nova-3", "keyterms": _keyterms(user)}},
            "think":  {
                "provider":  {"type": "open_ai", "model": "gpt-4o-mini", "temperature": 0.7},
                "functions": functions,
                "prompt":    SYSTEM_PROMPT + _known_user(user),
            },
            "speak":    {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
            "greeting": greeting,
        },
    }
