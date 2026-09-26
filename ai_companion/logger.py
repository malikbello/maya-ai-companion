"""
Logger: Comprehensive logging system for debugging end-to-end voice interactions.
Logs to both console and file for easy debugging.
Handles Windows encoding issues.
"""

import logging
import os
import sys
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Create logs directory
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Create timestamped log file
log_file = LOG_DIR / f"ai_companion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Setup logging with UTF-8 encoding
# INFO by default. At DEBUG, the websockets and HTTP client libraries log
# raw request headers, which include the Deepgram and OpenAI API keys.
_level = getattr(logging, os.getenv("MAYA_LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Header-level logging stays off even when MAYA_LOG_LEVEL=DEBUG.
for _noisy in ("websockets", "websockets.client", "httpx", "httpcore", "urllib3", "openai", "deepgram"):
    logging.getLogger(_noisy).setLevel(max(_level, logging.INFO))

# Get logger
logger = logging.getLogger("AI_Companion")
logger.info("=" * 60)
logger.info("AI COMPANION - LOGGING INITIALIZED")
logger.info(f"Log file: {log_file}")
logger.info("=" * 60)

def log_voice_input(text):
    """Log voice input from microphone"""
    logger.info(f"VOICE INPUT: {text}")

def log_ai_response(text):
    """Log AI response"""
    logger.info(f"AI RESPONSE: {text}")

def log_intent(intent, text):
    """Log detected intent"""
    logger.info(f"INTENT DETECTED: {intent} from '{text}'")

def log_error(component, error):
    """Log errors"""
    logger.error(f"ERROR in {component}: {error}")

def log_api_call(api_name, params):
    """Log API calls"""
    logger.debug(f"API CALL: {api_name} with {params}")

def log_reminder_trigger(reminder):
    """Log reminder trigger"""
    logger.info(f"REMINDER TRIGGERED: {reminder}")

def log_alarm_trigger(alarm):
    """Log alarm trigger"""
    logger.info(f"ALARM TRIGGERED: {alarm}")
