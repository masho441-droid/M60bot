
import os
from dotenv import load_dotenv

load_dotenv()

POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TZ: str = os.getenv("TZ", "UTC")

if not POLYGON_API_KEY or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    import logging
    logging.warning("One or more required environment variables are missing.")
