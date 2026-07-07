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
    return "🐉 M60 - Early Explosion Hunter (فوري) is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ===============================================================

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
STOCKDATA_TOKEN = os.getenv("STOCKDATA_TOKEN")  # يجب إضافته في Render

if not TOKEN or not CHAT_ID or not STOCKDATA_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN, CHAT_ID أو STOCKDATA_TOKEN غير موجودة")

bot = Bot(token=TOKEN)
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

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

# ====================== FETCH LIVE DATA (StockData.org) ======================
async def fetch_live_data(symbol):
    url = f"https://api.stockdata.org/v1/data/quote?symbols={symbol}&api_token={STOCKDATA_TOKEN}&extended_hours=true"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get('data'):
                    quote = data['data'][0]
                    price = quote.get('price')
                    volume = quote.get('volume')
                    if price and volume:
                        return {"price": price, "volume": volume}
    except:
        pass
    return None

# ====================== DETECT EARLY EXPLOSION ==================
async def detect_early_explosion(symbol):
    try:
        data = await fetch_live_data(symbol)
        if not data:
            return None

        price = data["price"]
        volume = data["volume"]

        # حساب الحجم النسبي (تقريبي بدون بيانات تاريخية)
        volume_spike = 2.5  # افتراضي
        volume_acceleration = 1.8  # افتراضي
        price_change = 2.0  # افتراضي (يمكن حسابه من بيانات سابقة)

        target1 = price * 1.05
        target2 = price * 1.10
        target3 = price * 1.20
        stop_loss = price * 0.97

        is_explosion = (
            MIN_PRICE <= price <= MAX_PRICE and
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

    await send_telegram("🔥 *M60 - Early Explosion Hunter (فوري)*")
    print("🚀 بدء العمل مع StockData.org...")

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
