import os
import asyncio
import time
import requests
import threading
from flask import Flask
from telegram import Bot

# ================= DUMMY WEB SERVER =================

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "iTick Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )

threading.Thread(target=run_web, daemon=True).start()

# ================= CONFIG =================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ITICK_TOKEN = os.getenv("ITICK_TOKEN")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN")

if not CHAT_ID:
    raise ValueError("Missing CHAT_ID")

bot = Bot(token=TOKEN)

# ================= HTTP SESSION =================

session = requests.Session()

session.headers.update({
    "User-Agent": "iTickScanner/2.0"
})

# ================= SETTINGS =================

MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_VOLUME = 100000

SLEEP_BETWEEN = 0.10

COOLDOWN = 300

UPDATE_INTERVAL = 10

BATCH_SIZE = 100

REQUEST_TIMEOUT = 15

MAX_RETRIES = 3

# ================= CACHE =================

PRICE_CACHE = {}

LAST_ALERT = {}

DAILY_ALERTS = {}

HOT_LIST = set()

PRICES_CACHE = {}

PRICES_CACHE_TIME = 0

symbols_cache = []

symbols_loaded = False

# ================= TELEGRAM =================

async def send(msg):
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ================= SOURCE 1: ITICK =================

def fetch_symbols_itick():
    """تحميل قائمة الأسهم من iTick"""

    if not ITICK_TOKEN:
        print("ITICK_TOKEN not found.")
        return None

    url = "https://api.itick.org/symbol/list"
    headers = {
        "accept": "application/json",
        "token": ITICK_TOKEN
    }

    params = {
        "type": "stock",
        "region": "US",
        "limit": 1000
    }

    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(
                url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if r.status_code != 200:
                print(f"iTick Symbols HTTP {r.status_code}")
                time.sleep(2)
                continue

            data = r.json()

            if data.get("code") != 0:
                print("iTick returned error:", data)
                return None

            symbols = []

            for item in data.get("data", []):

                symbol = (
                    item.get("symbol")
                    or item.get("code")
                )

                if symbol:
                    symbols.append(symbol)

            if symbols:
                print(f"[OK] Loaded {len(symbols)} symbols")
                return symbols

        except Exception as e:
            print(f"fetch_symbols_itick(): {e}")
            time.sleep(2)

    return None


def fetch_prices_itick(symbols):
    """تحميل الأسعار الحالية من iTick"""

    if not ITICK_TOKEN or not symbols:
        return {}

    prices = {}

    url = "https://api.itick.org/stock/quotes"

    headers = {
        "accept": "application/json",
        "token": ITICK_TOKEN
    }

    total_batches = (
        len(symbols) + BATCH_SIZE - 1
    ) // BATCH_SIZE

    for batch_no, i in enumerate(
        range(0, len(symbols), BATCH_SIZE),
        start=1
    ):

        batch = symbols[i:i + BATCH_SIZE]

        for attempt in range(MAX_RETRIES):

            try:

                params = {
                    "region": "US",
                    "codes": ",".join(batch)
                }

                r = session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT
                )

                if r.status_code == 429:
                    print("Rate limit... waiting")
                    time.sleep(5)
                    continue

                if r.status_code != 200:
                    print(f"Batch HTTP {r.status_code}")
                    break

                data = r.json()

                if data.get("code") != 0:
                    break

                quotes = data.get("data", {})

                for symbol, info in quotes.items():

                    price = float(info.get("ld", 0))

                    volume = int(info.get("v", 0))

                    if price > 0:

                        prices[symbol] = {
                            "price": price,
                            "volume": volume
                        }

                break

            except Exception as e:

                print(
                    f"Batch {batch_no}/{total_batches}: {e}"
                )

                time.sleep(2)

        time.sleep(0.20)

    print(f"[OK] Prices received: {len(prices)}")

    return prices

# ================= LOAD SYMBOLS =================

def load_symbols():
    global symbols_cache, symbols_loaded

    if symbols_loaded and symbols_cache:
        return symbols_cache

    symbols = fetch_symbols_itick()

    if symbols:
        symbols_loaded = True
        symbols_cache = symbols
        asyncio.create_task(send(f"✅ *تم تحميل {len(symbols)} سهم من iTick*"))
        return symbols

    # احتياطي: قائمة أساسية لتشغيل البوت
    fallback = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"]
    asyncio.create_task(send(f"⚠️ *استخدام القائمة الاحتياطية ({len(fallback)} سهم)*"))
    symbols_cache = fallback
    symbols_loaded = True
    return fallback

# ================= FETCH PRICES =================

def fetch_prices(symbols):
    global PRICES_CACHE, PRICES_CACHE_TIME
    
    now = time.time()
    if PRICES_CACHE and (now - PRICES_CACHE_TIME < UPDATE_INTERVAL):
        return PRICES_CACHE
    
    prices = fetch_prices_itick(symbols)
    
    if prices:
        PRICES_CACHE = prices
        PRICES_CACHE_TIME = now
        return prices
    
    return {}

# ================= MOMENTUM DETECTOR =================

def detect(symbol, price):
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {"previous": price, "current": price}
        return False

    previous = PRICE_CACHE[symbol]["current"]
    PRICE_CACHE[symbol]["previous"] = previous
    PRICE_CACHE[symbol]["current"] = price

    if previous <= 0:
        return False

    change = ((price - previous) / previous) * 100
    return change >= 0.12

# ================= COOLDOWN =================

def can_alert(symbol):
    now = time.time()
    if symbol in LAST_ALERT:
        if now - LAST_ALERT[symbol] < COOLDOWN:
            return False
    LAST_ALERT[symbol] = now
    return True

# ================= SIGNAL SCORE =================

def get_signal_score(change):
    if change >= 5:
        return 85
    elif change >= 3:
        return 70
    elif change >= 1:
        return 60
    elif change >= 0.5:
        return 50
    return 40

# ================= MAIN ENGINE =================

async def main():
    global DAILY_ALERTS

    await send("🔥 *الماسح الذكي بدأ العمل*")

    symbols = load_symbols()

    if not symbols:
        await send("❌ لم يتم تحميل قائمة الأسهم.")
        return

    print(f"Scanner started with {len(symbols)} symbols.")

    while True:

        try:

            all_prices = fetch_prices(symbols)

            if not all_prices:
                print("No prices received.")
                await asyncio.sleep(10)
                continue

            scanned = 0
            detected = 0

            for sym in symbols[:500]:

                data = all_prices.get(sym)

                if not data:
                    continue

                price = data["price"]
                volume = data.get("volume", 0)

                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue

                if volume < MIN_VOLUME:
                    continue

                scanned += 1

                if detect(sym, price):
                    HOT_LIST.add(sym)
                    detected += 1

                await asyncio.sleep(SLEEP_BETWEEN)

            print(
                f"Scanned={scanned}  "
                f"Hot={len(HOT_LIST)}  "
                f"Detected={detected}"
            )

            for sym in list(HOT_LIST):

                data = all_prices.get(sym)

                if not data:
                    HOT_LIST.discard(sym)
                    continue

                if not can_alert(sym):
                    continue

                price = data["price"]

                previous = PRICE_CACHE[sym]["previous"]

                if previous <= 0:
                    HOT_LIST.discard(sym)
                    continue

                change = ((price - previous) / previous) * 100

                score = get_signal_score(change)

                today = time.strftime("%Y-%m-%d")

                if today not in DAILY_ALERTS:
                    DAILY_ALERTS[today] = {}

                DAILY_ALERTS[today][sym] = (
                    DAILY_ALERTS[today].get(sym, 0) + 1
                )

                message = (
                    "🚨 *إشارة زخم جديدة* 🚨\n\n"
                    f"📊 الرمز: `{sym}`\n"
                    f"💰 السعر: `${price:.2f}`\n"
                    f"📈 التغير: `+{change:.2f}%`\n"
                    f"🔥 القوة: `{score}/100`\n"
                    f"🔢 رقم التنبيه: `{DAILY_ALERTS[today][sym]}`\n"
                    f"🕒 {time.strftime('%H:%M:%S')}\n\n"
                    "⚠️ ليست توصية استثمارية."
                )

                await send(message)

                HOT_LIST.discard(sym)

                await asyncio.sleep(0.3)

            if len(PRICE_CACHE) > 3000:
                PRICE_CACHE.clear()
                print("PRICE_CACHE cleared.")

            if len(LAST_ALERT) > 3000:
                LAST_ALERT.clear()

            await asyncio.sleep(5)

        except Exception as e:

            print(f"MAIN LOOP ERROR: {e}")

            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
