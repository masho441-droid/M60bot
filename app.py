import os
import asyncio
import time
import json
import websockets
import aiohttp
from telegram import Bot
from flask import Flask
import threading
from collections import deque

# ================= DUMMY WEB SERVER =================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "iTick WebSocket Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ITICK_TOKEN = os.getenv("ITICK_TOKEN")

if not TOKEN or not CHAT_ID or not ITICK_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN, CHAT_ID, or ITICK_TOKEN")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_VOLUME = 50000
MIN_MOMENTUM = 1.5
MIN_ACCELERATION = 0.3
MIN_VOLUME_SPIKE = 1.5

# ================= CACHE =================
PRICE_CACHE = {}
VOLUME_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ================= SIGNAL SCORE =================
def get_signal_score(momentum, acceleration, volume_spike):
    score = 0
    if momentum >= 5: score += 35
    elif momentum >= 3: score += 25
    elif momentum >= 1.5: score += 15
    if acceleration >= 1.5: score += 30
    elif acceleration >= 1.0: score += 20
    elif acceleration >= 0.3: score += 10
    if volume_spike >= 4.0: score += 35
    elif volume_spike >= 3.0: score += 25
    elif volume_spike >= 1.5: score += 15
    return min(score, 100)

def can_alert(symbol):
    now = time.time()
    if symbol in LAST_ALERT:
        if now - LAST_ALERT[symbol] < 300:
            return False
    LAST_ALERT[symbol] = now
    return True

def detect_surge(symbol, price, volume):
    now = time.time()
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {"previous": price, "current": price, "time": now}
        VOLUME_CACHE[symbol] = deque(maxlen=10)
        VOLUME_CACHE[symbol].append(volume)
        return False
    previous_price = PRICE_CACHE[symbol]["current"]
    PRICE_CACHE[symbol]["previous"] = previous_price
    PRICE_CACHE[symbol]["current"] = price
    PRICE_CACHE[symbol]["time"] = now
    VOLUME_CACHE[symbol].append(volume)
    if previous_price <= 0:
        return False
    momentum = ((price - previous_price) / previous_price) * 100
    acceleration = 0
    if len(PRICE_CACHE[symbol]) > 2:
        acceleration = momentum * 0.3
    volume_spike = 1.0
    if len(VOLUME_CACHE[symbol]) >= 5:
        avg_volume = sum(list(VOLUME_CACHE[symbol])[-5:]) / 5
        volume_spike = volume / avg_volume if avg_volume > 0 else 1.0
    is_surge = (
        momentum >= MIN_MOMENTUM and
        acceleration >= MIN_ACCELERATION and
        volume_spike >= MIN_VOLUME_SPIKE and
        volume >= MIN_VOLUME
    )
    if is_surge:
        return {
            "momentum": momentum,
            "acceleration": acceleration,
            "volume_spike": volume_spike,
            "volume": volume,
            "price": price
        }
    return False

# ================= جلب جميع الأسهم النشطة (شامل) =================
async def fetch_all_active_symbols():
    """جلب جميع الأسهم النشطة من TradingView (بدون قائمة ثابتة)"""
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "nempty"}
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
                    if len(d) >= 3 and d[1] is not None and d[2] is not None and d[2] > 50000:
                        symbols.append(d[0])
                return symbols[:500]
    except Exception as e:
        print(f"خطأ في جلب الأسهم: {e}")
        return []

# ================= WEB SOCKET مع تحديث القائمة ديناميكياً =================
async def itick_websocket():
    while True:
        try:
            symbols = await fetch_all_active_symbols()
            if not symbols:
                print("⚠️ لا توجد أسهم نشطة، إعادة المحاولة...")
                await asyncio.sleep(30)
                continue
            print(f"✅ تم جلب {len(symbols)} سهماً نشطاً")
            symbols_param = ",".join([f"{sym}$US" for sym in symbols[:500]])
            uri = "wss://api.itick.org/stock"
            headers = {"token": ITICK_TOKEN}
            async with websockets.connect(uri, extra_headers=headers) as websocket:
                print("✅ متصل بـ iTick WebSocket")
                subscribe_msg = {
                    "ac": "subscribe",
                    "params": symbols_param,
                    "types": "quote,tick"
                }
                await websocket.send(json.dumps(subscribe_msg))
                print(f"📡 تم الاشتراك في {len(symbols)} سهماً")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await process_websocket_data(data)
                    except Exception as e:
                        print(f"خطأ في المعالجة: {e}")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            await asyncio.sleep(5)

# ================= PROCESS WEBSOCKET DATA =================
async def process_websocket_data(data):
    symbol = data.get("symbol")
    price = data.get("price") or data.get("ld")
    volume = data.get("volume") or data.get("v")
    if not symbol or not price:
        return
    surge_data = detect_surge(symbol, price, volume)
    if surge_data and can_alert(symbol):
        momentum = surge_data["momentum"]
        acceleration = surge_data["acceleration"]
        volume_spike = surge_data["volume_spike"]
        current_price = surge_data["price"]
        score = get_signal_score(momentum, acceleration, volume_spike)
        today = time.strftime("%Y-%m-%d")
        if today not in DAILY_ALERTS:
            DAILY_ALERTS[today] = {}
        DAILY_ALERTS[today][symbol] = DAILY_ALERTS[today].get(symbol, 0) + 1
        msg = (
            f"🚨 *اندفاع مفاجئ* 🚨\n\n"
            f"📊 الرمز: `{symbol}`\n"
            f"💰 السعر: `${current_price:.2f}`\n"
            f"📈 الزخم: `+{momentum:.2f}%`\n"
            f"🚀 التسارع: `+{acceleration:.2f}%`\n"
            f"📊 الحجم النسبي: `{volume_spike:.1f}x`\n"
            f"🔥 القوة: `{score}/100`\n"
            f"🔢 التنبيه: `{DAILY_ALERTS[today][symbol]}`\n"
            f"🕒 {time.strftime('%H:%M:%S')}\n\n"
            f"⚠️ للمتابعة فقط"
        )
        await send(msg)
        print(f"📤 تم إرسال تنبيه لـ {symbol}")

# ================= MAIN =================
async def main():
    await send("🔥 *الماسح الشامل - استراتيجية الاندفاع المفاجئ*")
    print("🚀 بدء تشغيل الماسح الشامل...")
    await itick_websocket()

if __name__ == "__main__":
    asyncio.run(main())
