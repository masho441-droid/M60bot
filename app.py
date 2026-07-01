import os
import asyncio
import aiohttp
import time
import yfinance as yf
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== DUMMY WEB SERVER ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Real Liquidity Hunter is running", 200

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
MAX_PRICE = 3.0
MIN_VOLUME_SPIKE = 2.5
MIN_VOLUME_ACCELERATION = 1.5
MIN_CONSECUTIVE_ACCELERATION = 3
SMA20_LOOKBACK = 20
MAX_SPREAD_RATIO = 0.02
ALERT_COOLDOWN = 1800

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(NY_TZ).date()

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ====================== DETECT LIQUIDITY =======================
async def detect_real_liquidity(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        hist = stock.history(period="2d", interval="5m")
        if hist.empty or len(hist) < 20:
            return None

        # البيانات الحالية
        current = hist.iloc[-1]
        price = current["Close"]
        volume = current["Volume"]
        high = current["High"]
        low = current["Low"]

        # الحجم النسبي
        avg_volume_10 = hist["Volume"].iloc[-10:].mean()
        volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 0

        # تسارع الحجم (مقارنة بالشمعة السابقة)
        prev_volume = hist["Volume"].iloc[-2] if len(hist) > 1 else volume
        volume_acceleration = volume / prev_volume if prev_volume > 0 else 0

        # استمرارية التسارع (آخر 3 شموع)
        volumes = hist["Volume"].iloc[-4:].tolist()
        consecutive_acceleration = all(volumes[i] > volumes[i-1] for i in range(1, len(volumes)))

        # SMA20
        closes = hist["Close"].iloc[-SMA20_LOOKBACK:]
        sma20 = closes.mean() if len(closes) >= SMA20_LOOKBACK else price
        price_above_sma20 = price > sma20

        # الفجوة السعرية (Spread)
        spread = (high - low) / price if price > 0 else 1
        low_spread = spread < MAX_SPREAD_RATIO

        # الأخبار السلبية (محاكاة)
        news_negative = False

        # التحقق من شروط السيولة الحقيقية
        is_real_liquidity = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume_spike >= MIN_VOLUME_SPIKE and
            volume_acceleration >= MIN_VOLUME_ACCELERATION and
            consecutive_acceleration and
            price_above_sma20 and
            low_spread and
            not news_negative
        )

        if is_real_liquidity:
            now_ny = datetime.now(NY_TZ)
            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": volume_spike,
                "volume_acceleration": volume_acceleration,
                "consecutive_acceleration": consecutive_acceleration,
                "sma20": sma20,
                "spread": spread,
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
            return symbols[:300]
    except Exception as e:
        print(f"❌ فشل جلب القائمة: {e}")
        return []

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date

    await send_telegram("🔥 *M60 - صياد السيولة الحقيقية (Real Liquidity Hunter)*")
    print("🚀 بدء العمل...")

    while True:
        try:
            now_ny = datetime.now(NY_TZ)
            if now_ny.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_ny.date()

            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة")
                    await asyncio.sleep(60)
                    continue

                print(f"🔍 فحص {len(symbols)} سهماً...")
                tasks = [detect_real_liquidity(symbol) for symbol in symbols]
                results = await asyncio.gather(*tasks)

                for data in results:
                    if data and can_alert(data["symbol"]):
                        alert_counters[data["symbol"]] = alert_counters.get(data["symbol"], 0) + 1
                        alert_num = alert_counters[data["symbol"]]

                        msg = (
                            f"💧 *سيولة حقيقية - دخول أموال ذكية*\n\n"
                            f"📊 الرمز: `{data['symbol']}`\n"
                            f"💰 السعر: `${data['price']:.2f}`\n"
                            f"📈 الحجم النسبي: `{data['volume_spike']:.1f}x`\n"
                            f"⚡ تسارع الحجم: `{data['volume_acceleration']:.1f}x`\n"
                            f"📊 استمرار التسارع: `{'✅' if data['consecutive_acceleration'] else '❌'}`\n"
                            f"📈 SMA20: `${data['sma20']:.2f}`\n"
                            f"📉 الفجوة السعرية: `{data['spread']*100:.2f}%`\n"
                            f"🕒 وقت الكشف (نيويورك): `{data['time']}`\n"
                            f"🔢 تنبيه #{alert_num} لهذا السهم\n\n"
                            f"✅ سيولة حقيقية - راقب السهم فوراً"
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
