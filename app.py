import asyncio
import logging
import threading
import os
from datetime import datetime

from flask import Flask, jsonify
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot import build_application, send_scheduled_report
from scheduler import ReportScheduler
from market_data import get_daily_bars, MarketDataError
from indicators import calculate_pivot, calculate_trend, calculate_atr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

flask_app = Flask(__name__)
_bot_app = None
_last_report_time = None
_bot_loop = None


def _start_bot_and_scheduler() -> None:
    """تشغيل البوت في thread منفصل مع event loop مستقل."""
    global _bot_app, _last_report_time, _bot_loop
    
    try:
        _bot_app = build_application()
        
        _bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bot_loop)

        async def runner():
            global _last_report_time
            await _bot_app.initialize()
            await _bot_app.start()
            await _bot_app.updater.start_polling()

            async def send_wrapper():
                global _last_report_time
                await send_scheduled_report(_bot_app)
                _last_report_time = datetime.utcnow().isoformat()

            scheduler = ReportScheduler(send_callback=send_wrapper)
            scheduler.start()

        _bot_loop.run_until_complete(runner())
        _bot_loop.run_forever()
        
    except Exception as exc:
        logger.exception("Bot failed to start: %s", exc)


@flask_app.route("/")
def index():
    return jsonify({"status": "ok", "service": "spx-bot"})


@flask_app.route("/health")
def health():
    return jsonify({"status": "healthy", "last_report": _last_report_time})


@flask_app.route("/report")
def report_json():
    try:
        bars = get_daily_bars(limit=60)
        pivot = calculate_pivot(bars)
        trend = calculate_trend(bars)
        atr = calculate_atr(bars)
        return jsonify({"pivot": pivot, "trend": trend, "atr": atr})
    except MarketDataError as exc:
        return jsonify({"error": str(exc)}), 503


# بدء البوت في thread منفصل بمجرد استيراد التطبيق
threading.Thread(target=_start_bot_and_scheduler, daemon=True).start()


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.critical("Missing required environment variables.")
        raise SystemExit(1)

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
