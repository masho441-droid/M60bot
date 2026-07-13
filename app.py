import os
import asyncio
import aiohttp
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== DUMMY WEB SERVER ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Fixed Symbols Hunter is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ===============================================================

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
STOCKDATA_TOKEN = os.getenv("STOCKDATA_TOKEN")

if not TOKEN or not CHAT_ID or not STOCKDATA_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN, CHAT_ID أو STOCKDATA_TOKEN غير موجودة")

bot = Bot(token=TOKEN)
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.1
MAX_PRICE = 5.0
MIN_VOLUME = 200000
MIN_VOLUME_SPIKE = 5.0
MIN_PRICE_CHANGE = 5.0
ALERT_COOLDOWN = 1800  # 30 دقيقة

# ====================== FIXED SYMBOLS LIST ======================
SYMBOLS = [
    "YMAT", "RBNE", "ENLV", "PFSA", "NCRA", "CGTL", "SRXH", "SNAL", "SLAI",
    "NVVE", "NTCL", "NIVF", "NIPG", "JZ", "INLF", "HKIT", "CRIS", "ABTC",
    "GMEX", "RMTI", "MQ", "ALIT", "TRNR", "QNCX", "JBDI", "HCWB", "ZCMD",
    "PAVS", "MNDR", "GIBO", "GDC", "VRAX", "RUBI", "NUWE", "AMIX", "YYGH",
    "ILLR", "FCUV", "WLDS", "POM", "LHSW", "LABT", "BOXL", "BMGL", "WOK",
    "FRTK", "MIMI", "SOBR"
]

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(MAKKAH_TZ).date()
last_premarket_sent = False
last_market_open_sent = False

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ====================== FETCH QUOTES (StockData.org) ============
async def fetch_quotes(session):
    if not SYMBOLS:
        return []
    
    symbols_param = ",".join(SYMBOLS)
    url = f"https://api.stockdata.org/v1/data/quote?symbols={symbols_param}&api_token={STOCKDATA_TOKEN}&extended_hours=true"
    
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                print(f"❌ فشل جلب البيانات: {resp.status}")
                return []
            data = await resp.json()
            quotes = data.get('data', [])
            print(f"✅ تم جلب {len(quotes)} سهماً من StockData.org")
            return quotes
    except Exception as e:
        print(f"❌ خطأ في StockData.org: {e}")
        return []

# ====================== DETECT EXPLOSION ========================
def detect_explosion(quote):
    try:
        symbol = quote.get('symbol')
        price = quote.get('price')
        volume = quote.get('volume')
        change = quote.get('change_percent', 0)

        if not symbol or not price or not volume:
            return None

        volume_spike = 3.0  # افتراضي (يمكن حسابه من بيانات تاريخية)

        target1 = price * 1.20
        target2 = price * 1.50
        target3 = price * 2.00
        stop_loss = price * 0.95

        is_explosion = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume >= MIN_VOLUME and
            volume_spike >= MIN_VOLUME_SPIKE and
            change > MIN_PRICE_CHANGE
        )

        if is_explosion:
            now_ny = datetime.now(NY_TZ)
            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": volume_spike,
                "price_change": change,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "stop_loss": stop_loss,
                "time": now_ny.strftime("%H:%M")
            }
        return None
    except Exception as e:
        print(f"⚠️ خطأ في تحليل {quote.get('symbol')}: {e}")
        return None

def can_alert(symbol):
    now = time.time()
    if symbol in alert_history:
        if now - alert_history[symbol] < ALERT_COOLDOWN:
            return False
    alert_history[symbol] = now
    return True

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date, last_premarket_sent, last_market_open_sent

    await send_telegram("🔥 *M60 - Fixed Symbols Hunter يعمل*")
    print("🚀 بدء العمل مع قائمة ثابتة...")

    while True:
        try:
            now_makkah = datetime.now(MAKKAH_TZ)
            now_hour = now_makkah.hour
            now_minute = now_makkah.minute

            if now_hour == 11 and now_minute == 0 and not last_premarket_sent:
                await send_telegram("🌅 *بداية البري ماركت (11 ص بتوقيت مكة)*")
                last_premarket_sent = True
                print("✅ تم إرسال رسالة البري ماركت")

            if now_hour == 16 and now_minute == 30 and not last_market_open_sent:
                await send_telegram("🔔 *افتتاح السوق الرسمي (4:30 م بتوقيت مكة)*")
                last_market_open_sent = True
                print("✅ تم إرسال رسالة افتتاح السوق")

            if now_hour == 0 and now_minute == 0:
                last_premarket_sent = False
                last_market_open_sent = False

            if now_makkah.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_makkah.date()
                print("✅ تم إعادة ضبط العدادات اليومية")

            async with aiohttp.ClientSession() as session:
                quotes = await fetch_quotes(session)
                if not quotes:
                    print("⚠️ لا توجد بيانات من StockData.org")
                    await asyncio.sleep(30)
                    continue

                for quote in quotes:
                    result = detect_explosion(quote)
                    if result and can_alert(result["symbol"]):
                        alert_counters[result["symbol"]] = alert_counters.get(result["symbol"], 0) + 1
                        alert_num = alert_counters[result["symbol"]]

                        msg = (
                            f"💥 *انفجار مبكر - سيولة قوية*\n\n"
                            f"📊 الرمز: `{result['symbol']}`\n"
                            f"💰 السعر: `${result['price']:.2f}`\n"
                            f"📈 الحجم النسبي: `{result['volume_spike']:.1f}x`\n"
                            f"📈 الزخم: `+{result['price_change']:.2f}%`\n"
                            f"🎯 الأهداف: `{result['target1']:.2f}` → `{result['target2']:.2f}` → `{result['target3']:.2f}`\n"
                            f"🛑 وقف الخسارة: `{result['stop_loss']:.2f}`\n"
                            f"🕒 وقت الكشف (نيويورك): `{result['time']}`\n"
                            f"🔢 تنبيه #{alert_num} لهذا السهم\n\n"
                            f"⚠️ راقب السهم فوراً"
                        )
                        await send_telegram(msg)
                        print(f"✅ تم إرسال تنبيه لـ {result['symbol']}")
                        await asyncio.sleep(1)

                print(f"⏳ انتظار 60 ثانية...")
                await asyncio.sleep(60)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
