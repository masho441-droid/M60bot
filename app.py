import os
import asyncio
import aiohttp
import time
import yfinance as yf
from datetime import datetime, timedelta
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== DUMMY WEB SERVER ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Early Explosion Hunter (محدث) is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ===============================================================

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("❌ TELEGRAM_TOKEN أو CHAT_ID غير موجودة")

bot = Bot(token=TOKEN)
NY_TZ = pytz.timezone('America/New_York')

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_VOLUME_SPIKE = 2.5
MIN_VOLUME_ACCELERATION = 1.8
MIN_VOLUME = 500000
MIN_CHANGE = 0.8
ALERT_COOLDOWN = 1800  # 30 دقيقة

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(NY_TZ).date()
last_premarket_sent = False
last_market_open_sent = False

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ====================== DETECT EARLY EXPLOSION ==================
async def detect_early_explosion(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="5d", interval="5m")
        if hist.empty or len(hist) < 10:
            return None

        current = hist.iloc[-1]
        price = current["Close"]
        volume = current["Volume"]

        avg_volume_10 = hist["Volume"].iloc[-10:].mean()
        volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 0

        volume_last_5 = hist["Volume"].iloc[-5:].mean()
        volume_acceleration = volume / volume_last_5 if volume_last_5 > 0 else 0

        price_change = ((price - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2]) * 100 if len(hist) > 1 else 0

        target1 = price * 1.05
        target2 = price * 1.10
        target3 = price * 1.20
        stop_loss = price * 0.97

        is_explosion = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume_spike >= MIN_VOLUME_SPIKE and
            volume_acceleration >= MIN_VOLUME_ACCELERATION and
            volume >= MIN_VOLUME and
            price_change > MIN_CHANGE
        )

        if is_explosion:
            now_ny = datetime.now(NY_TZ)
            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": volume_spike,
                "volume_acceleration": volume_acceleration,
                "price_change": price_change,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "stop_loss": stop_loss,
                "time": now_ny.strftime("%H:%M"),
                "hour": now_ny.hour,
                "minute": now_ny.minute
            }
        return None
    except Exception as e:
        print(f"⚠️ فشل فحص {symbol}: {e}")
        return None

def can_alert(symbol):
    now = time.time()
    if symbol in alert_history:
        if now - alert_history[symbol] < ALERT_COOLDOWN:
            return False
    alert_history[symbol] = now
    return True

# ====================== FETCH SYMBOLS ===========================
async def fetch_active_symbols(session):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]}
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "volume"]
    }
    try:
        async with session.post(url, json=payload, timeout=15) as resp:
            data = await resp.json()
            symbols = []
            for item in data.get('data', []):
                d = item['d']
                if len(d) >= 3 and None not in [d[1], d[2]]:
                    symbols.append(d[0])
            return symbols[:200]
    except Exception as e:
        print(f"❌ فشل جلب القائمة: {e}")
        return []

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date, last_premarket_sent, last_market_open_sent

    await send_telegram("🔥 *M60 - Early Explosion Hunter (محدث)*")
    print("🚀 بدء العمل...")

    while True:
        try:
            now_ny = datetime.now(NY_TZ)
            now_hour = now_ny.hour
            now_minute = now_ny.minute

            # ======== رسائل الترحيب ========
            if now_hour == 11 and now_minute == 0 and not last_premarket_sent:
                await send_telegram("🌅 *بداية البري ماركت*")
                last_premarket_sent = True
                print("✅ تم إرسال رسالة البري ماركت")

            if now_hour == 16 and now_minute == 30 and not last_market_open_sent:
                await send_telegram("🔔 *افتتاح السوق الرسمي*")
                last_market_open_sent = True
                print("✅ تم إرسال رسالة افتتاح السوق")

            if now_hour == 0 and now_minute == 0:
                last_premarket_sent = False
                last_market_open_sent = False

            # ======== إعادة ضبط العدادات اليومية ========
            if now_ny.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_ny.date()
                print("✅ تم إعادة ضبط العدادات اليومية")

            # ======== جلب الأسهم ========
            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة")
                    await asyncio.sleep(30)
                    continue

                print(f"🔍 جاري فحص {len(symbols)} سهماً...")

                tasks = [detect_early_explosion(symbol) for symbol in symbols]
                results = await asyncio.gather(*tasks)

                for data in results:
                    if data and can_alert(data["symbol"]):
                        alert_counters[data["symbol"]] = alert_counters.get(data["symbol"], 0) + 1
                        alert_num = alert_counters[data["symbol"]]

                        msg = (
                            f"💥 *انفجار مبكر - سيولة قوية*\n\n"
                            f"📊 الرمز: `{data['symbol']}`\n"
                            f"💰 السعر: `${data['price']:.2f}`\n"
                            f"📈 الحجم النسبي: `{data['volume_spike']:.1f}x`\n"
                            f"⚡ تسارع الحجم: `{data['volume_acceleration']:.1f}x`\n"
                            f"📈 الزخم: `+{data['price_change']:.2f}%`\n"
                            f"🎯 الأهداف: `{data['target1']:.2f}` → `{data['target2']:.2f}` → `{data['target3']:.2f}`\n"
                            f"🛑 وقف الخسارة: `{data['stop_loss']:.2f}`\n"
                            f"🕒 وقت الكشف (نيويورك): `{data['time']}`\n"
                            f"🔢 تنبيه #{alert_num} لهذا السهم\n\n"
                            f"⚠️ راقب السهم فوراً"
                        )
                        await send_telegram(msg)
                        print(f"✅ تم إرسال تنبيه لـ {data['symbol']}")
                        await asyncio.sleep(1)

                print(f"⏳ انتظار 60 ثانية...")
                await asyncio.sleep(60)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
