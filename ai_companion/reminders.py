"""
Reminders: User-specific reminder management with proper time handling.
"""

import json
from datetime import datetime
from user_manager import get_current_user


def load_reminders():
    """Load reminders for current user."""
    user = get_current_user()
    return user.get_reminders()


def save_reminders(reminders):
    """Save reminders for current user."""
    user = get_current_user()
    user.save_reminders(reminders)


def add_reminder(time_str: str, message: str):
    """
    Add a reminder with proper validation.
    
    Args:
        time_str: Time in format "YYYY-MM-DD HH:MM" (already formatted by parser)
        message: Reminder task description
    """
    if not time_str or not message:
        print("❌ Invalid reminder data")
        return False

    reminders = load_reminders()
    
    try:
        # Validate time format
        datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError as e:
        print(f"❌ Invalid time format: {e}")
        return False

    reminders.append({
        "datetime": time_str,
        "message": message,
        "done": False,
        "created_at": datetime.now().isoformat()
    })

    save_reminders(reminders)
    print(f"✅ Reminder set: {message} at {time_str}")
    return True


def _parse_reminder_time(time_str: str) -> datetime:
    """Try multiple datetime formats to parse a reminder time string."""
    formats = [
        "%Y-%m-%d %H:%M:%S",       # 2026-05-21 13:15:42  (canonical)
        "%Y-%m-%d %H:%M",          # 2026-05-21 13:15  (older entries)
        "%Y-%m-%d at %I:%M %p",    # 2026-05-21 at 1:15 PM
        "%Y-%m-%d at %I %p",       # 2026-05-21 at 1 PM
        "%Y-%m-%dT%H:%M:%S",       # ISO format
        "%Y-%m-%dT%H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(time_str.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse reminder time: '{time_str}'")


def check_reminders():
    """
    Check for reminders that are due.
    Returns list of reminder messages that are due.
    """
    reminders = load_reminders()
    now = datetime.now()
    due = []

    changed = False
    for r in reminders:
        if r.get("done"):
            continue

        try:
            if "datetime" in r:
                reminder_time = _parse_reminder_time(r["datetime"])
            elif "time" in r:
                today = now.strftime("%Y-%m-%d")
                reminder_time = _parse_reminder_time(f"{today} {r['time']}")
            else:
                continue

            if reminder_time <= now:
                due.append(r.get("message", r.get("description", "Reminder")))
                r["done"] = True
                changed = True

        except Exception as e:
            print(f"⚠️ Error checking reminder: {e} — auto-dismissing")
            r["done"] = True  # prevent repeated errors on malformed reminders
            changed = True

    if changed:
        save_reminders(reminders)

    return due


def delete_reminder(index: int):
    """Delete a specific reminder."""
    reminders = load_reminders()
    if 0 <= index < len(reminders):
        del reminders[index]
        save_reminders(reminders)
        return True
    return False


def list_reminders():
    """List all pending reminders for current user."""
    reminders = load_reminders()
    pending = [r for r in reminders if not r.get("done")]
    return pending
