import logging
import requests
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("AI_Companion")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message: str, chat_id=None) -> bool:
    """
    Core function: send a Telegram message via the bot.
    Returns True on success, False on failure.
    """
    if not BOT_TOKEN:
        logger.warning("Telegram BOT token not configured.")
        return False

    chat_id = chat_id or DEFAULT_CHAT_ID
    if not chat_id:
        logger.warning("Telegram chat ID not configured.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        logger.error(f"Telegram API error {response.status_code}: {response.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram connection error: {e}")
        return False


# ------------------------------------------------------------------ #
# Voice-callable functions (return spoken strings for MAYA to read)
# ------------------------------------------------------------------ #

DOCTOR_CHAT_ID = os.getenv("TELEGRAM_DOCTOR_CHAT_ID")
DOCTOR_NAME = os.getenv("DOCTOR_NAME", "your doctor")


def message_doctor(text: str, sender: str = "") -> dict:
    """Send a note to the user's doctor on Telegram.

    The doctor opens the bot once (/start); their chat ID then goes in
    TELEGRAM_DOCTOR_CHAT_ID. A bot cannot message someone who has never
    started it, so there is deliberately no fallback to another chat.
    """
    if not BOT_TOKEN or not DOCTOR_CHAT_ID:
        return {"sent": False, "result": "Your doctor isn't connected on Telegram yet. Add TELEGRAM_DOCTOR_CHAT_ID to the .env file."}
    who = sender if sender and sender != "User" else "your patient"
    body = f"Message from {who}, sent by MAYA:\n\n{text.strip()}"
    if send_telegram_message(body, chat_id=DOCTOR_CHAT_ID):
        return {"sent": True, "result": f"Sent to {DOCTOR_NAME} on Telegram."}
    return {"sent": False, "result": "I couldn't reach Telegram just now. Please try again in a moment."}


def send_voice_message(text: str) -> str:
    """
    Voice command: send a custom text message via Telegram.
    Example trigger: 'Send a message saying I will be home late'
    """
    if not BOT_TOKEN or not DEFAULT_CHAT_ID:
        return (
            "Telegram is not configured. "
            "Please add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your .env file."
        )
    success = send_telegram_message(text)
    if success:
        return "Done. Your message has been sent via Telegram."
    return "I could not send the Telegram message right now. Please check your connection or .env settings."


def send_health_report_telegram() -> str:
    """
    Voice command: manually trigger a health report to be sent via Telegram.
    Example trigger: 'Send my health report to Telegram'
    """
    try:
        from health_report import generate_weekly_report
        report = generate_weekly_report()
        success = send_telegram_message(report)
        if success:
            return "Your health report has been sent via Telegram."
        return "I generated your report but could not send it via Telegram right now."
    except Exception as e:
        logger.error(f"Health report telegram error: {e}")
        return "I could not generate or send the health report right now."


def check_telegram_status() -> str:
    """
    Voice command: confirm whether Telegram is configured and working.
    Example trigger: 'Is Telegram set up?'
    """
    if not BOT_TOKEN:
        return "Telegram is not set up. The bot token is missing from your .env file."
    if not DEFAULT_CHAT_ID:
        return "Telegram bot token is set, but no chat ID is configured in your .env file."

    # Quick connectivity check via getMe
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            bot_name = response.json().get("result", {}).get("first_name", "your bot")
            return f"Telegram is configured and working. Your bot is called {bot_name}."
        return "Telegram token is set but the bot is not responding. Check the token."
    except Exception:
        return "Telegram is configured but I could not reach the Telegram servers right now."
