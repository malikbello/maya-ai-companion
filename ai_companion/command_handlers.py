"""
Command Handlers: Execute actual commands (time, weather, alarms, reminders)
These are called BEFORE sending to LLM to provide real data
"""

from datetime import datetime
from user_manager import get_current_user
import re
from weather import get_weather

try:
    from logger import logger
except ImportError:
    import logging
    logger = logging.getLogger("Commands")


def handle_time_command(text: str) -> str:
    """Handle 'what time is it' requests"""
    current_time = datetime.now().strftime("%I:%M %p")
    return f"The current time is {current_time}."


def handle_date_command(text: str) -> str:
    """Handle 'what date is it' requests"""
    current_date = datetime.now().strftime("%A, %B %d, %Y")
    return f"Today is {current_date}."


def handle_weather_command(text: str) -> str:
    """Handle weather requests - get location from user profile and fetch real weather"""
    try:
        user = get_current_user()
        location = user.data.get("location", None)
        
        if not location or location.lower() in ["unknown", "not set"]:
            return "I don't know your location yet. Could you tell me what city or area you're in? Then I can help with weather!"
        
        # Get real-time weather from OpenWeather API
        logger.info(f"[COMMAND] Weather request for {location}")
        weather_info = get_weather(location)
        return weather_info
    except Exception as e:
        logger.error(f"Weather command error: {e}")
        return "I couldn't fetch the weather right now. Could you tell me your location?"


def handle_check_alarms(text: str) -> str:
    """Check user's alarms"""
    try:
        user = get_current_user()
        alarms = user.get_alarms()
        
        if not alarms:
            return "You don't have any alarms set."
        
        response = "Your alarms are:\n"
        for alarm in alarms:
            response += f"- {alarm.get('description', 'Alarm')} at {alarm.get('time', 'unknown time')}\n"
        return response.strip()
    except Exception as e:
        logger.error(f"Error checking alarms: {e}")
        return "I couldn't retrieve your alarms."


def handle_set_alarm(text: str) -> str:
    """Set a new alarm - MUST have explicit action words"""
    try:
        # STRICT: Only match if we can find BOTH an action word AND a time
        # Patterns: "set alarm for 7 AM", "wake me at 6:30 AM", etc.
        action_words = r'(?:set|create|make|add|wake)\s+(?:an?\s+)?alarm|(?:wake|alarm)\s+me'
        
        if not re.search(action_words, text, re.IGNORECASE):
            return None  # No alarm action word found
        
        # Extract the time
        time_match = re.search(r'(?:for|at|at the)\s+(\d{1,2})(?:[:.]?(\d{2}))?\s*(am|pm|AM|PM|a\.m\.|p\.m\.)', text, re.IGNORECASE)
        
        if not time_match:
            return "Could you tell me what time you want to set the alarm for? For example: 7 AM or 2:30 PM"
        
        time_str = time_match.group(0).strip()
        time_str = re.sub(r'a\.m\.', 'AM', time_str, flags=re.IGNORECASE)
        time_str = re.sub(r'p\.m\.', 'PM', time_str, flags=re.IGNORECASE)
        
        # Extract description (what the alarm is for)
        description = "Alarm"
        if "wake" in text.lower():
            description = "Wake up alarm"
        else:
            # Check if there's a specific purpose mentioned
            for_match = re.search(r'(?:to|for)\s+([a-z\s]+?)(?:at|for the)', text, re.IGNORECASE)
            if for_match:
                desc_text = for_match.group(1).strip()
                if desc_text and len(desc_text) < 30 and desc_text not in ['an alarm', 'alarm', 'me']:
                    description = desc_text.capitalize()
        
        user = get_current_user()
        alarm_data = {
            'time': time_str,
            'description': description,
            'enabled': True,
            'created_at': datetime.now().isoformat()
        }
        user.add_alarm(alarm_data)
        logger.info(f"[ALARM SET] Successfully set: {description} at {time_str}")
        return f"Got it! I've set your alarm for {time_str}. {description}."
    except Exception as e:
        logger.error(f"Error setting alarm: {e}")
        return None


def handle_check_reminders(text: str) -> str:
    """Check user's reminders"""
    try:
        user = get_current_user()
        reminders = user.get_reminders()
        
        if not reminders:
            return "You don't have any reminders set."
        
        response = "Your reminders are:\n"
        for reminder in reminders:
            response += f"- {reminder.get('description', 'Reminder')} at {reminder.get('time', 'unknown time')}\n"
        return response.strip()
    except Exception as e:
        logger.error(f"Error checking reminders: {e}")
        return "I couldn't retrieve your reminders."


def handle_set_reminder(text: str) -> str:
    """Set a new reminder - MUST have explicit action words"""
    try:
        # STRICT: Only match if "remind me" is in the text (not just casual mentions)
        if "remind me" not in text.lower():
            return None  # Not a reminder request
        
        # Extract time - supports various formats like "at 3 PM", "in 2 hours", "for tomorrow"
        time_match = re.search(r'(?:at|for|in)\s+(\d{1,2})(?:[:.]?(\d{2}))?\s*(am|pm|AM|PM|a\.m\.|p\.m\.)', text, re.IGNORECASE)
        
        if not time_match:
            return "When would you like to be reminded? (e.g., at 3 PM or in 2 hours)"
        
        time_str = time_match.group(0).strip()
        time_str = re.sub(r'a\.m\.', 'AM', time_str, flags=re.IGNORECASE)
        time_str = re.sub(r'p\.m\.', 'PM', time_str, flags=re.IGNORECASE)
        
        # Extract what to remind about (text between "remind me" and the time)
        description_match = re.search(r'remind me\s+(?:to\s+)?(.+?)(?:\s+(?:at|for|in)\s+\d|$)', text, re.IGNORECASE)
        description = "Reminder"
        if description_match:
            desc_candidate = description_match.group(1).strip()
            if desc_candidate and len(desc_candidate) < 50 and desc_candidate.lower() not in ["reminder", "something", "to"]:
                description = desc_candidate
        
        user = get_current_user()
        user.add_reminder({
            'time': time_str,
            'description': description,
            'created_at': datetime.now().isoformat()
        })
        
        logger.info(f"[REMINDER SET] {description} at {time_str}")
        return f"Got it! I'll remind you to {description} at {time_str}."
    except Exception as e:
        logger.error(f"Error setting reminder: {e}")
        return None


def handle_location_command(text: str) -> str:
    """Extract and save user's location."""
    try:
        # Extract location from common patterns
        location_match = re.search(r"(?:i'm|i am|located|in|from)\s+(?:in\s+)?([A-Za-z\s]+?)(?:and|\.|,|$)", text, re.IGNORECASE)
        
        if location_match:
            location = location_match.group(1).strip()
            # Clean up the location string
            location = re.sub(r'\b(and|in|from|located)\b', '', location, flags=re.IGNORECASE).strip()
            
            if location and len(location) < 50:  # Sanity check
                user = get_current_user()
                user.set_location(location)
                logger.info(f"[LOCATION] Set user location to: {location}")
                return f"Got it! I've saved that you're in {location}. Now I can help with location-specific info!"
        
        return "Could you tell me what city or area you're in?"
    except Exception as e:
        logger.error(f"Location command error: {e}")
        return "I couldn't parse your location. Could you tell me your city?"


def handle_set_name(name: str) -> str:
    try:
        name = name.strip().title()
        user = get_current_user()
        user.update_name(name)
        logger.info(f"[NAME] Set user name to: {name}")
        return f"Got it! I'll call you {name} from now on."
    except Exception as e:
        logger.error(f"Set name error: {e}")
        return "I had trouble saving your name, but I'll remember it for this session."


def handle_set_location(city: str) -> str:
    """Save the user's city/location to their profile."""
    try:
        city = city.strip().title()
        user = get_current_user()
        user.data["location"] = city
        user.save_profile()
        logger.info(f"[LOCATION] Set user location to: {city}")
        return f"Got it! I've saved that you're in {city}. I can now fetch weather for you there."
    except Exception as e:
        logger.error(f"Set location error: {e}")
        return "I had trouble saving your location."


def handle_set_alarm_direct(time_str: str, label: str = "") -> str:
    """
    Set an alarm directly from structured agent parameters.
    Bypasses regex parsing — uses _normalize_time on the clean time string.
    """
    try:
        from alarms import _normalize_time
        normalized = _normalize_time(time_str)
        if not normalized:
            return f"I couldn't understand the alarm time '{time_str}'. Try saying '7 AM' or '14:30'."
        note = label.strip() if label and label.strip() else "Alarm"
        user = get_current_user()
        user.add_alarm({
            "time": normalized,
            "note": note,
            "description": note,
            "enabled": True,
            "last_triggered": None,
            "created_at": datetime.now().isoformat(),
        })
        logger.info(f"[ALARM SET] '{note}' at {normalized}")
        return f"Done! Alarm set for {time_str}."
    except Exception as e:
        logger.error(f"Direct alarm set error: {e}")
        return "I had trouble setting that alarm."


_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "fifty": 50, "sixty": 60,
}


def _relative_delta(text: str):
    """'in 5 minutes', '1 minute', 'in one hour', 'half an hour' -> timedelta.
    The model often drops the 'in', and speech gives number words."""
    import re as _re
    from datetime import timedelta
    t = text.strip().lower()
    if _re.fullmatch(r"(in\s+)?(half an hour|30 min(ute)?s?)", t):
        return timedelta(minutes=30)
    m = _re.fullmatch(r"(?:in\s+)?(\d+|[a-z-]+)\s+(minutes?|mins?|hours?|hrs?)(?:\s+from now)?", t)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS.get(m.group(1))
    if not n:
        return None
    return timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n)


def handle_set_reminder_direct(task: str, time_str: str = "") -> str:
    """
    Set a reminder directly from structured agent parameters.
    Converts the time string to an absolute datetime and stores it.
    """
    try:
        from datetime import timedelta
        now = datetime.now()
        reminder_dt = None

        if time_str:
            # Strip leading "at"/"for" so strptime sees clean time
            import re as _re
            clean = _re.sub(r'^(?:at\s+the\s+|at\s+|for\s+)', '', time_str.strip(), flags=_re.IGNORECASE).strip()

            # Relative time: "in 5 minutes", "1 minute", "in one hour", "half an hour"
            delta = _relative_delta(clean)
            if delta:
                reminder_dt = now + delta

            # Absolute time formats
            if not reminder_dt:
                for fmt in ["%I:%M %p", "%I %p", "%H:%M", "%I:%M%p", "%I%p"]:
                    try:
                        t = datetime.strptime(clean.upper(), fmt)
                        reminder_dt = now.replace(hour=t.hour, minute=t.minute,
                                                  second=0, microsecond=0)
                        # If that time has already passed today, schedule for tomorrow
                        if reminder_dt <= now:
                            reminder_dt += timedelta(days=1)
                        break
                    except ValueError:
                        continue

        user = get_current_user()
        if reminder_dt:
            dt_str = reminder_dt.strftime("%Y-%m-%d %H:%M")
            # Format for speech with colon: "3:52 PM" not "352 PM" or "03:52 PM"
            spoken_time = reminder_dt.strftime("%I:%M %p").lstrip("0")
            user.add_reminder({
                "datetime": dt_str,
                "message": task,
                "done": False,
                "created_at": now.isoformat(),
            })
            logger.info(f"[REMINDER SET] '{task}' at {dt_str}")
            return f"Reminder set for {spoken_time}: {task}."
        else:
            # Could not parse the time — tell the LLM to ask the user to clarify
            logger.warning(f"[REMINDER] Could not parse time: '{time_str}'")
            return f"I could not understand '{time_str}' as a time. Please ask the user to say when they want the reminder, for example '3:30 PM' or 'in 20 minutes'."
    except Exception as e:
        logger.error(f"Direct reminder set error: {e}")
        return "I had trouble setting that reminder."


def handle_command(intent: str, text: str) -> tuple:
    """
    Handle a command and return (response, should_skip_llm)
    If should_skip_llm is True, don't send to LLM
    """
    
    if intent == "time":
        return handle_time_command(text), True
    elif intent == "date":
        return handle_date_command(text), True
    elif intent == "weather":
        return handle_weather_command(text), True
    elif intent == "location":
        return handle_location_command(text), True
    elif intent == "check_alarm":
        return handle_check_alarms(text), True
    elif intent == "alarm":
        return handle_set_alarm(text), False  # May need LLM for clarification
    elif intent == "check_reminder":
        return handle_check_reminders(text), True
    elif intent == "reminder":
        return handle_set_reminder(text), False  # May need LLM for clarification
    
    return None, False
