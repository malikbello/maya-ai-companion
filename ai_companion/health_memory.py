import copy
import json
import os
from datetime import datetime, date, timedelta

FILE_NAME = "health_profile.json"

DEFAULT_PROFILE = {
    # Identity
    "name": "User",
    "age": None,
    # Medical
    "conditions": [],
    "medications": [],        # [{name, dosage, times}]
    "emergency_contact": None,
    "doctor_contact": None,
    # Daily state
    "sleep_hours_avg": None,
    "sleep_quality": None,
    "stress_level": None,
    "hydration_today": 0,
    "hydration_goal": 8,
    # Timestamps
    "last_check_in": None,
    "last_report_sent": None,
    # History logs (kept for _MAX_LOG days)
    "sleep_log": [],       # [{date, hours, quality}]
    "mood_log": [],        # [{date, mood, score}]
    "symptom_log": [],     # [{date, symptom, severity}]
    "exercise_log": [],    # [{date, activity, duration_minutes}]
    "medication_log": [],  # [{date, name, taken}]
    "hydration_log": [],   # [{date, glasses}]
}

_MAX_LOG = 30


def load_profile():
    # deep copies: a shallow copy shares the log lists, so every appended
    # entry would leak into DEFAULT_PROFILE and from there into new profiles
    if not os.path.exists(FILE_NAME):
        profile = copy.deepcopy(DEFAULT_PROFILE)
        save_profile(profile)
        return profile
    with open(FILE_NAME, "r") as f:
        profile = json.load(f)
    # Backward compat: add any new fields silently
    changed = False
    for key, default in DEFAULT_PROFILE.items():
        if key not in profile:
            profile[key] = copy.deepcopy(default)
            changed = True
    if changed:
        save_profile(profile)
    return profile


def save_profile(profile):
    with open(FILE_NAME, "w") as f:
        json.dump(profile, f, indent=4)


def update_field(key, value):
    profile = load_profile()
    profile[key] = value
    save_profile(profile)


def set_emergency_contact(number):
    profile = load_profile()
    if not number.startswith("+") or not number[1:].isdigit():
        return "Invalid number format. Use international format like +2348012345678."
    profile["emergency_contact"] = number
    save_profile(profile)
    return f"Emergency contact set to {number}."


def get_emergency_contact():
    return load_profile().get("emergency_contact")


def log_checkin():
    update_field("last_check_in", datetime.now().isoformat())


def mark_report_sent():
    update_field("last_report_sent", datetime.now().isoformat())


def report_sent_today():
    last = load_profile().get("last_report_sent")
    if not last:
        return False
    return datetime.now().date() == datetime.fromisoformat(last).date()


def append_to_log(log_key, entry):
    """Append an entry dict to a named log list, trimming to _MAX_LOG entries."""
    profile = load_profile()
    log = profile.get(log_key, [])
    log.append(entry)
    if len(log) > _MAX_LOG:
        log = log[-_MAX_LOG:]
    profile[log_key] = log
    save_profile(profile)


def get_log_entries(log_key, days=7):
    """Return log entries from the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [e for e in load_profile().get(log_key, []) if e.get("date", "") >= cutoff]


def reset_hydration_if_new_day():
    """If last check-in was on a previous day, archive hydration and reset counter."""
    profile = load_profile()
    last = profile.get("last_check_in")
    if not last:
        return
    last_date = datetime.fromisoformat(last).date()
    if last_date < date.today():
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        log = profile.get("hydration_log", [])
        log.append({"date": yesterday, "glasses": profile.get("hydration_today", 0)})
        if len(log) > _MAX_LOG:
            log = log[-_MAX_LOG:]
        profile["hydration_log"] = log
        profile["hydration_today"] = 0
        save_profile(profile)


def needs_daily_checkin():
    profile = load_profile()
    last = profile.get("last_check_in")

    if not last:
        return True

    last_time = datetime.fromisoformat(last)
    return datetime.now().date() != last_time.date()
