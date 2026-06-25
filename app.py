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
POLYGON_KEY = os.getenv("POLYGON_KEY", "cr5n9nujPulQqkLwnqpszcON1jh")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing TELEGRAM_TOKEN or CHAT_ID")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_MARKET_CAP = 10_000_000   # 10 مليون
MAX_MARKET_CAP = 300_000_000  # 300 مليون
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

# ================= LOAD SYMBOLS WITH FILTERS =================
def load_symbols_with_filters():
    """جلب الأسهم التي تطابق شروط السعر والقيمة السوقية"""
    try:
        # 1. جلب جميع الأسهم
        url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&limit=1000&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=30)
        data = r.json()
        all_tickers = data.get("results", [])

        filtered_symbols = []
        for ticker in all_tickers:
            # 2. فلترة حسب القيمة السوقية
            market_cap = ticker.get("market_cap", 0)
            if market_cap < MIN_MARKET_CAP or market_cap > MAX_MARKET_CAP:
                continue
            filtered_symbols.append(ticker["ticker"])

        print(f"Loaded {len(filtered_symbols)} symbols after filtering")
        return filtered_symbols

    except Exception as e:
        print(f"Error loading symbols: {e}")
        return []

# ================= FETCH ALL PRICES (ONE REQUEST) =================
def fetch_all_prices():
    """جلب بيانات جميع الأسهم في طلب واحد"""
    today = time.strftime("%Y-%m-%d")
    url = f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{today}?adjusted=true&apiKey={POLYGON_KEY}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return {}
        data = r.json()
        results = data.get("results", [])
        # بناء قاموس: {الرمز: السعر}
        return {item["T"]: item["c"] for item in results if "c" in item}
    except:
        return {}

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

    await send("🔥 *الماسح الشامل (Polygon) - فلتر السعر والقيمة السوقية*")

    symbols = load_symbols_with_filters()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم تطابق الفلتر. تحقق من المفتاح أو الإعدادات.")
        return

    while True:
        try:
            # 1. جلب بيانات جميع الأسهم دفعة واحدة
            all_prices = fetch_all_prices()
            if not all_prices:
                await asyncio.sleep(60)
                continue

            # 2. فحص جميع الأسهم
            for sym in symbols:
                price = all_prices.get(sym)
                if not price:
                    continue

                # فلترة السعر
                if price < MIN_PRICE or price > MAX_PRICE:
                    continue

                if detect(sym, price):
                    HOT_LIST.add(sym)

                await asyncio.sleep(SLEEP_BATCH)

            # 3. فحص الأسهم الساخنة
            for sym in list(HOT_LIST):
                price = all_prices.get(sym)
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
                        f"💰 السعر: `${price:.2f}`\n"
                        f"📈 نسبة نجاح الصفقة: `{success_rate}%`\n"
                        f"🕒 الوقت: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    )

                    await send(msg)

                await asyncio.sleep(HOT_SLEEP)

            # تحديث القائمة كل ساعة
            await asyncio.sleep(3600)

        except Exception as e:
            print(f"Main loop error: {e}")
            await asyncio.sleep(60)

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
