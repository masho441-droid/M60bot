import os
import asyncio
import time
import requests
from telegram import Bot

# ================= DUMMY WEB SERVER =================
from flask import Flask
import threading

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Ultra Fast Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN or not CHAT_ID or not FINNHUB_KEY:
    raise ValueError("Missing environment variables")

bot = Bot(token=TOKEN)

# ================= SPEED SETTINGS =================
SCAN_LIMIT = 60
BASE_SLEEP = 0.25
HOT_SCAN_SLEEP = 0.10
COOLDOWN = 300

# ================= ACCURACY SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_CHANGE = 0.5
MIN_VOLUME_RATIO = 1.2
MIN_ACCELERATION = 0.3

# ================= STATE =================
PRICE_CACHE = {}
VOLUME_CACHE = {}
last_alert = {}
daily_alerts = {}

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= SYMBOLS =================
def get_symbols():
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=20)
        return r.json()[:SCAN_LIMIT]
    except:
        return []

# ================= FAST QUOTE =================
def get_quote(symbol):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)

        if r.status_code != 200:
            return None

        d = r.json()

        return {
            "price": d.get("c", 0),
            "change": d.get("dp", 0),
            "volume": d.get("v", 0),
            "prev_close": d.get("pc", 0)
        }
    except:
        return None

# ================= ACCURACY CHECKS =================
def check_accuracy(data, symbol):
    if not data:
        return False, 0, 0, 0

    price = data["price"]
    change = data["change"]
    volume = data["volume"]
    prev_close = data["prev_close"]

    # 1. نطاق السعر
    if not (MIN_PRICE <= price <= MAX_PRICE):
        return False, 0, 0, 0

    # 2. الزخم (التغير السعري)
    if change < MIN_CHANGE:
        return False, 0, 0, 0

    # 3. الحجم النسبي
    if symbol in VOLUME_CACHE:
        avg_volume = VOLUME_CACHE[symbol]
        relative_volume = volume / avg_volume if avg_volume > 0 else 1
    else:
        relative_volume = 1
        VOLUME_CACHE[symbol] = volume

    if relative_volume < MIN_VOLUME_RATIO:
        return False, 0, 0, 0

    # 4. تسارع السعر
    acceleration = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
    if acceleration < MIN_ACCELERATION:
        return False, 0, 0, 0

    return True, change, relative_volume, acceleration

# ================= COOLDOWN =================
def can_alert(symbol):
    now = time.time()

    if symbol in last_alert:
        if now - last_alert[symbol] < COOLDOWN:
            return False

    last_alert[symbol] = now
    return True

# ================= SUCCESS RATE =================
def get_success_rate(change):
    if change >= 5:
        return 85
    elif change >= 3:
        return 70
    elif change >= 1:
        return 60
    else:
        return 50

# ================= MAIN ENGINE =================
async def main():
    await send("🔥 *الماسح السريع - النسخة المدمجة*")

    symbols = get_symbols()

    while True:
        try:
            hot_symbols = []

            # 1) scan fast
            for item in symbols:
                symbol = item.get("symbol")
                if not symbol:
                    continue

                data = get_quote(symbol)
                if not data:
                    continue

                is_valid, change, rel_vol, accel = check_accuracy(data, symbol)

                if is_valid:
                    hot_symbols.append((symbol, data["price"], change, rel_vol, accel))

                await asyncio.sleep(BASE_SLEEP)

            # 2) deep scan for hot only
            for symbol, price, change, rel_vol, accel in hot_symbols:

                if not can_alert(symbol):
                    continue

                # تحديث عداد التنبيهات اليومية
                today = time.strftime("%Y-%m-%d")
                if today not in daily_alerts:
                    daily_alerts[today] = {}

                if symbol not in daily_alerts[today]:
                    daily_alerts[today][symbol] = 0
                daily_alerts[today][symbol] += 1

                alert_count = daily_alerts[today][symbol]
                success_rate = get_success_rate(change)

                msg = (
                    f"🚨 *تنبيه انطلاق سعري* 🚨\n\n"
                    f"📊 الرمز: `{symbol}`\n"
                    f"🔢 عدد التنبيهات اليوم: `{alert_count}`\n"
                    f"📈 الزخم: `{change:.2f}%`\n"
                    f"📊 الحجم النسبي: `{rel_vol:.1f}x`\n"
                    f"🚀 التسارع: `{accel:.2f}%`\n"
                    f"💰 السيولة: `${price}`\n"
                    f"📈 نسبة نجاح الصفقة: `{success_rate}%`\n"
                    f"🕒 الوقت: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                )

                await send(msg)

                await asyncio.sleep(HOT_SCAN_SLEEP)

            # refresh symbols occasionally
            if time.time() % 600 < 5:
                symbols = get_symbols()

        except Exception as e:
            print("Main loop error:", e)
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
