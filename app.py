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
    return "🐉 M60 - Final Hunter is running", 200

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
MIN_VOLUME_SPIKE = 3.0
MIN_VOLUME_ACCELERATION = 2.0
MIN_FIRST_MINUTE_VOLUME = 150000
ALERT_COOLDOWN = 1800

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(NY_TZ).date()
volume_cache = {}

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

def can_alert(symbol):
    now = time.time()
    if symbol in alert_history:
        if now - alert_history[symbol] < ALERT_COOLDOWN:
            return False
    alert_history[symbol] = now
    return True

# ====================== FETCH LIVE DATA (Yahoo Finance) =========
async def fetch_live_data(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                result = data.get('chart', {}).get('result', [])
                if not result:
                    return None
                meta = result[0].get('meta', {})
                price = meta.get('regularMarketPrice')
                volume = meta.get('regularMarketVolume')
                if not price or not volume:
                    return None
                return {"price": price, "volume": volume}
    except:
        return None

# ====================== DETECT EXPLOSION ========================
async def detect_explosion(symbol):
    data = await fetch_live_data(symbol)
    if not data:
        return None

    price = data["price"]
    volume = data["volume"]

    if not price or not volume or price <= 0 or volume <= 0:
        return None

    last_volume = volume_cache.get(symbol, volume)
    volume_spike = volume / last_volume if last_volume > 0 else 1.0
    volume_cache[symbol] = volume

    volume_acceleration = 2.0 if volume > last_volume * 1.5 else 1.0

    target1 = price * 1.05
    target2 = price * 1.10
    target3 = price * 1.20
    stop_loss = price * 0.97

    is_explosion = (
        MIN_PRICE <= price <= MAX_PRICE and
        volume_spike >= MIN_VOLUME_SPIKE and
        volume_acceleration >= MIN_VOLUME_ACCELERATION and
        volume >= MIN_FIRST_MINUTE_VOLUME
    )

    if is_explosion and can_alert(symbol):
        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
        alert_num = alert_counters[symbol]
        now_ny = datetime.now(NY_TZ)

        return {
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "volume_spike": volume_spike,
            "volume_acceleration": volume_acceleration,
            "target1": target1,
            "target2": target2,
            "target3": target3,
            "stop_loss": stop_loss,
            "alert_num": alert_num,
            "time": now_ny.strftime("%H:%M")
        }
    return None

# ====================== FETCH SYMBOLS ===========================
async def fetch_active_symbols():
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                data = await resp.json()
                symbols = []
                for item in data.get('data', []):
                    d = item['d']
                    if len(d) >= 3 and None not in [d[1], d[2]]:
                        symbols.append(d[0])
                return symbols[:200]
    except:
        return []

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date

    await send_telegram("🔥 *M60 - Final Hunter يعمل*")
    print("🚀 بدء العمل...")

    while True:
        try:
            now_ny = datetime.now(NY_TZ)
            if now_ny.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_ny.date()

            symbols = await fetch_active_symbols()
            if not symbols:
                print("⚠️ لا توجد أسهم نشطة")
                await asyncio.sleep(30)
                continue

            print(f"🔍 فحص {len(symbols)} سهماً...")

            for symbol in symbols:
                result = await detect_explosion(symbol)
                if result:
                    msg = (
                        f"💥 *انفجار مبكر - سيولة قوية*\n\n"
                        f"📊 الرمز: `{result['symbol']}`\n"
                        f"💰 السعر: `${result['price']:.2f}`\n"
                        f"📈 الحجم النسبي: `{result['volume_spike']:.1f}x`\n"
                        f"⚡ تسارع الحجم: `{result['volume_acceleration']:.1f}x`\n"
                        f"📊 السيولة: `{result['volume']:,}`\n"
                        f"🎯 الأهداف: `{result['target1']:.2f}` → `{result['target2']:.2f}` → `{result['target3']:.2f}`\n"
                        f"🛑 وقف الخسارة: `{result['stop_loss']:.2f}`\n"
                        f"🕒 وقت الكشف: `{result['time']}`\n"
                        f"🔢 تنبيه #{result['alert_num']} لهذا السهم\n\n"
                        f"⚠️ راقب السهم فوراً"
                    )
                    await send_telegram(msg)
                    await asyncio.sleep(1)

            print(f"⏳ انتظار 20 ثانية...")
            await asyncio.sleep(20)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main_loop())
