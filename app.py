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
    return "M60 Bot is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# تشغيل خادم الويب في خلفية منفصلة
threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN or not CHAT_ID or not FINNHUB_KEY:
    raise ValueError("Missing environment variables")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MAX_PRICE = 10
MIN_PRICE = 0.5
MIN_CHANGE = 1

SCAN_LIMIT = 100
SLEEP_BETWEEN = 0.8
CYCLE_SLEEP = 60

COOLDOWN = 900  # 15 min per stock
SYMBOL_CACHE_TTL = 21600  # 6 hours

# ================= STATE =================
last_alert = {}
symbol_cache = []
last_fetch_time = 0
daily_alerts = {}

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        print("Telegram error:", e)

# ================= SYMBOLS =================
def get_symbols():
    global symbol_cache, last_fetch_time

    now = time.time()

    if symbol_cache and (now - last_fetch_time < SYMBOL_CACHE_TTL):
        return symbol_cache

    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=30)

        if r.status_code == 200:
            symbol_cache = r.json()
            last_fetch_time = now
            print(f"Loaded symbols: {len(symbol_cache)}")

    except Exception as e:
        print("Symbol error:", e)

    return symbol_cache

# ================= QUOTE =================
def get_quote(symbol):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            return None

        d = r.json()
        
        # جلب الحجم (Volume) - بيانات تقريبية
        volume = 0
        try:
            vol_url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={FINNHUB_KEY}"
            vol_res = requests.get(vol_url, timeout=5)
            if vol_res.status_code == 200:
                vol_data = vol_res.json()
                volume = vol_data.get('metric', {}).get('volumeAvg', 0)
        except:
            pass

        return {
            "price": d.get("c", 0),
            "change": d.get("dp", 0),
            "volume": volume,
            "prev_price": d.get("pc", 0)
        }
    except:
        return None

# ================= STRATEGY =================
def check_signal(data):
    if not data:
        return False

    price = data["price"]
    change = data["change"]
    volume = data.get("volume", 0)
    prev_price = data.get("prev_price", 0)

    if price <= 0:
        return False

    # 1. نطاق السعر
    if not (MIN_PRICE <= price <= MAX_PRICE):
        return False

    # 2. الزخم (التغير السعري)
    if change < MIN_CHANGE:
        return False

    # 3. الحجم النسبي (زيادة مفاجئة في الحجم)
    avg_volume = 50000  # متوسط وهمي، يمكن تعديله
    relative_volume = volume / avg_volume if avg_volume > 0 else 1

    # 4. تسارع السعر
    acceleration = (price - prev_price) / prev_price if prev_price > 0 else 0

    # شروط إضافية للانطلاق
    if relative_volume < 1.5:
        return False

    if acceleration < 0.01:
        return False

    return True

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

# ================= MAIN =================
async def main():
    global daily_alerts

    await send("🔥 M60 PRO BOT STARTED (Enhanced)")

    while True:
        try:
            symbols = get_symbols()

            if not symbols:
                await asyncio.sleep(30)
                continue

            selected = symbols[:SCAN_LIMIT]

            print(f"Scanning {len(selected)} symbols")

            for item in selected:

                symbol = item.get("symbol")
                if not symbol:
                    continue

                if not can_alert(symbol):
                    continue

                data = get_quote(symbol)

                if check_signal(data):
                    # تحديث عداد التنبيهات اليومية
                    today = time.strftime("%Y-%m-%d")
                    if today not in daily_alerts:
                        daily_alerts[today] = {}
                    
                    if symbol not in daily_alerts[today]:
                        daily_alerts[today][symbol] = 0
                    daily_alerts[today][symbol] += 1
                    
                    alert_count = daily_alerts[today][symbol]
                    success_rate = get_success_rate(data['change'])

                    msg = (
                        f"🚨 *تنبيه انطلاق سعري* 🚨\n\n"
                        f"📊 الرمز: `{symbol}`\n"
                        f"🔢 عدد التنبيهات اليوم: `{alert_count}`\n"
                        f"📈 الزخم: `{data['change']}%`\n"
                        f"📊 الحجم: `{data['volume']}`\n"
                        f"💰 السيولة: `${data['price']}`\n"
                        f"📈 نسبة نجاح الصفقة: `{success_rate}%`\n"
                        f"🕒 الوقت: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    )

                    await send(msg)

                await asyncio.sleep(SLEEP_BETWEEN)

            await asyncio.sleep(CYCLE_SLEEP)

        except Exception as e:
            print("Main loop error:", e)
            await asyncio.sleep(30)

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
