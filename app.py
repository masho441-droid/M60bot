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
    return "Polygon Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
POLYGON_KEY = os.getenv("POLYGON_KEY")

if not TOKEN or not CHAT_ID or not POLYGON_KEY:
    raise ValueError("Missing environment variables")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
BATCH_SIZE = 120
SLEEP_BATCH = 0.2
HOT_SLEEP = 0.05
COOLDOWN = 300

PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= LOAD UNIVERSE =================
def load_symbols():
    try:
        url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&limit=1000&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=30)
        data = r.json()
        return [x["ticker"] for x in data.get("results", [])]
    except:
        return []

# ================= QUOTE =================
def get_price(symbol):
    try:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        results = data.get("results", [])
        if results:
            return results[0].get("c", 0)  # سعر الإغلاق
        return None
    except:
        return None

# ================= MOMENTUM =================
def detect(symbol, price):
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = price
        return False

    old = PRICE_CACHE[symbol]
    PRICE_CACHE[symbol] = price

    if old <= 0:
        return False

    change = ((price - old) / old) * 100

    if change >= 0.12:
        return True

    return False

# ================= COOLDOWN =================
def can_alert(symbol):
    now = time.time()
    if symbol in LAST_ALERT:
        if now - LAST_ALERT[symbol] < COOLDOWN:
            return False
    LAST_ALERT[symbol] = now
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
    global DAILY_ALERTS

    await send("🔥 *الماسح باستخدام Polygon*")

    symbols = load_symbols()
    index = 0

    while True:
        try:
            batch = symbols[index:index + BATCH_SIZE]

            if not batch:
                index = 0
                continue

            # ================= BATCH SCAN =================
            for sym in batch:
                price = get_price(sym)
                if not price:
                    continue

                if detect(sym, price):
                    HOT_LIST.add(sym)

                await asyncio.sleep(SLEEP_BATCH)

            # ================= HOT LIST SCAN =================
            for sym in list(HOT_LIST):
                price = get_price(sym)
                if not price:
                    continue

                if can_alert(sym):
                    today = time.strftime("%Y-%m-%d")
                    if today not in DAILY_ALERTS:
                        DAILY_ALERTS[today] = {}

                    if sym not in DAILY_ALERTS[today]:
                        DAILY_ALERTS[today][sym] = 0
                    DAILY_ALERTS[today][sym] += 1

                    alert_count = DAILY_ALERTS[today][sym]
                    change = ((price - PRICE_CACHE.get(sym, price)) / PRICE_CACHE.get(sym, price)) * 100 if PRICE_CACHE.get(sym, 0) > 0 else 0
                    success_rate = get_success_rate(change)

                    msg = (
                        f"🚨 *تنبيه انطلاق سعري* 🚨\n\n"
                        f"📊 الرمز: `{sym}`\n"
                        f"🔢 عدد التنبيهات اليوم: `{alert_count}`\n"
                        f"📈 الزخم: `{change:.2f}%`\n"
                        f"📊 الحجم: `غير متاح`\n"
                        f"💰 السيولة: `${price}`\n"
                        f"📈 نسبة نجاح الصفقة: `{success_rate}%`\n"
                        f"🕒 الوقت: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    )

                    await send(msg)

                await asyncio.sleep(HOT_SLEEP)

            index += BATCH_SIZE

            if index >= len(symbols):
                index = 0

        except Exception:
            await asyncio.sleep(2)

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
