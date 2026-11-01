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
_last_report_time = None

async def run_bot():
    """تشغيل البوت مع إعادة المحاولة عند الفشل"""
    global _last_report_time
    
    while True:
        try:
            app = build_application()
            await app.initialize()
            await app.start()
            await app.updater.start_polling()

            async def send_wrapper():
                global _last_report_time
                await send_scheduled_report(app)
                _last_report_time = datetime.utcnow().isoformat()

            scheduler = ReportScheduler(send_callback=send_wrapper)
            scheduler.start()

            # الحفاظ على البوت يعمل
            await asyncio.Event().wait()
            
        except Exception as exc:
            logger.exception("Bot crashed, restarting in 10 seconds: %s", exc)
            await asyncio.sleep(10)

def start_bot_thread():
    """تشغيل البوت في thread منفصل"""
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())
        
    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    logger.info("Bot thread started.")

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

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.critical("Missing required environment variables.")
        raise SystemExit(1)

    # بدء البوت في الخلفية
    start_bot_thread()

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
