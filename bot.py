import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from market_data import get_daily_bars, get_previous_close, MarketDataError
from indicators import calculate_pivot, calculate_trend, calculate_atr
from report import build_report

logger = logging.getLogger(__name__)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("👋 مرحباً! أنا بوت SPX.\n\n/report — تقرير SPX الآن\n/status — حالة البوت\n/help — المساعدة")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📖 الأوامر المتاحة:\n/report — إرسال تقرير SPX فوراً\n/status — حالة البوت\n/help — هذه القائمة")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"✅ البوت يعمل.\nChat ID: {TELEGRAM_CHAT_ID}")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        bars = get_daily_bars(limit=60)
        pivot = calculate_pivot(bars)
        trend = calculate_trend(bars)
        atr = calculate_atr(bars)
        prev_close = get_previous_close()
        text = build_report(pivot, trend, atr, prev_close)
        await update.message.reply_text(text, parse_mode="HTML")
    except MarketDataError as exc:
        logger.error("Market data error: %s", exc)
        await update.message.reply_text("⚠️ فشل جلب بيانات السوق. حاول لاحقاً.")
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        await update.message.reply_text("⚠️ خطأ غير متوقع.")

async def send_scheduled_report(app: Application) -> None:
    try:
        bars = get_daily_bars(limit=60)
        pivot = calculate_pivot(bars)
        trend = calculate_trend(bars)
        atr = calculate_atr(bars)
        prev_close = get_previous_close()
        text = build_report(pivot, trend, atr, prev_close)
        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")
        logger.info("Scheduled report sent to chat %s", TELEGRAM_CHAT_ID)
    except Exception as exc:
        logger.error("Failed to send scheduled report: %s", exc)

def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("report", cmd_report))
    return app
