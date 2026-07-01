import os
import asyncio
import aiohttp
import time
import yfinance as yf
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading

# ====================== DUMMY WEB SERVER ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Hidden Hunter is running", 200

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

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.5
MAX_PRICE = 3.0
MIN_VOLUME_SPIKE = 2.5
MIN_VOLUME_ACCELERATION = 1.8
BREAKOUT_MINUTES = 15
MIN_FLOAT_SHRINK = 0.8  # انخفاض عدد الأسهم المتداولة
ALERT_COOLDOWN = 1800  # 30 دقيقة

# ====================== CACHE ===================================
alert_history = {}
daily_counter = 0
last_reset_date = datetime.now().date()
price_cache = {}
volume_cache = {}

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ====================== DETECT SURGE ===========================
async def detect_surge(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        hist = stock.history(period="1d", interval="5m")
        if hist.empty or len(hist) < 10:
            return None

        # البيانات الحالية
        current = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else current
        price = current["Close"]
        volume = current["Volume"]
        prev_volume = prev["Volume"]
        high = current["High"]
        prev_high = hist["High"].iloc[-10:].max()

        # الحجم النسبي
        avg_volume_10 = hist["Volume"].iloc[-10:].mean()
        volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 0

        # تسارع السيولة
        volume_acceleration = volume / prev_volume if prev_volume > 0 else 0

        # كسر القمة
        breakout = price > prev_high * 0.99

        # حجم التداول الحر (تقديري)
        float_shares = info.get("sharesOutstanding", 0) * 0.2
        if float_shares > 0:
            float_shrink = 1 - (volume / float_shares)
        else:
            float_shrink = 0

        # الأخبار (محاكاة)
        news_negative = False  # يمكن استبدالها بـ API أخبار

        # التحقق من الشروط
        is_surge = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume_spike >= MIN_VOLUME_SPIKE and
            volume_acceleration >= MIN_VOLUME_ACCELERATION and
            breakout and
            float_shrink >= MIN_FLOAT_SHRINK and
            not news_negative
        )

        if is_surge:
            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": volume_spike,
                "volume_acceleration": volume_acceleration,
                "breakout": breakout,
                "float_shrink": float_shrink,
                "time": datetime.now().strftime("%H:%M")
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
            return symbols[:300]
    except Exception as e:
        print(f"❌ فشل جلب القائمة: {e}")
        return []

# ====================== MAIN LOOP ===============================
async def main_loop():
    global daily_counter, last_reset_date

    await send_telegram("🔥 *M60 - Hidden Hunter (استراتيجية الانفجار السعري)*")
    print("🚀 بدء العمل...")

    while True:
        try:
            now = datetime.now()
            if now.date() != last_reset_date:
                daily_counter = 0
                last_reset_date = now.date()

            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة")
                    await asyncio.sleep(60)
                    continue

                print(f"🔍 فحص {len(symbols)} سهماً...")
                tasks = [detect_surge(symbol) for symbol in symbols]
                results = await asyncio.gather(*tasks)

                for data in results:
                    if data and can_alert(data["symbol"]):
                        daily_counter += 1
                        msg = (
                            f"🚀 *انفجار سعري محتمل*\n\n"
                            f"📊 الرمز: `{data['symbol']}`\n"
                            f"💰 السعر: `${data['price']:.2f}`\n"
                            f"📈 الحجم النسبي: `{data['volume_spike']:.1f}x`\n"
                            f"⚡ تسارع الحجم: `{data['volume_acceleration']:.1f}x`\n"
                            f"🔥 كسر القمة: `{'✅' if data['breakout'] else '❌'}`\n"
                            f"📉 انخفاض الأسهم الحرة: `{data['float_shrink']*100:.0f}%`\n"
                            f"🕒 وقت الكشف: `{data['time']}`\n"
                            f"🔢 التنبيه اليومي: `#{daily_counter}`\n\n"
                            f"⚠️ للمتابعة الفورية"
                        )
                        await send_telegram(msg)
                        await asyncio.sleep(1)

                print(f"⏳ انتظار 60 ثانية...")
                await asyncio.sleep(60)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
