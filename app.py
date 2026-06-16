import asyncio
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# التوكن ومعرف القناة
TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"

# دالة جلب البيانات (خارجية وبسيطة)
def get_data():
    try:
        url = "https://scanner.tradingview.com/america/scan"
        headers = {"User-Agent": "Mozilla/5.0"}
        payload = {"filter": [{"left": "close", "operation": "in_range", "right": [0.5, 6.0]}], "columns": ["name", "close"]}
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        return res.json().get("data", [])
    except:
        return []

# دالة التنبيه
async def monitor(context: ContextTypes.DEFAULT_TYPE):
    data = get_data()
    if data:
        msg = f"🔍 تم العثور على {len(data)} فرصة"
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ البوت يعمل الآن")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    # إضافة الأوامر
    app.add_handler(CommandHandler("start", start))
    
    # إضافة مهمة المراقبة التلقائية
    job_queue = app.job_queue
    job_queue.run_repeating(monitor, interval=60, first=10)
    
    print("--- البوت يعمل الآن بكامل طاقته ---")
    app.run_polling()
