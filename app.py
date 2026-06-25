import os
import asyncio
import time
import requests
import yfinance as yf
from telegram import Bot

# ================= DUMMY WEB SERVER =================
from flask import Flask
import threading

flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Smart Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
POLYGON_KEY = os.getenv("POLYGON_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing TELEGRAM_TOKEN or CHAT_ID")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10
SLEEP_BATCH = 0.2
HOT_SLEEP = 0.05
COOLDOWN = 300
UPDATE_INTERVAL = 60

PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()
PRICES_CACHE = {}
PRICES_CACHE_TIME = 0

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= LOAD SYMBOLS (USING POLYGON) =================
def load_symbols_polygon():
    if not POLYGON_KEY:
        return None
    try:
        url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&limit=1000&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"Polygon error: {r.status_code}")
            return None
        data = r.json()
        return [x["ticker"] for x in data.get("results", []) if "ticker" in x]
    except Exception as e:
        print(f"Polygon load error: {e}")
        return None

# ================= LOAD SYMBOLS (FINNHUB FALLBACK) =================
def load_symbols_finnhub():
    if not FINNHUB_KEY:
        return None
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        return [x["symbol"] for x in data if "symbol" in x]
    except:
        return None

def load_symbols():
    symbols = load_symbols_polygon()
    if symbols:
        asyncio.create_task(send(f"✅ *تم تحميل {len(symbols)} سهم من Polygon*"))
        return symbols
    
    symbols = load_symbols_finnhub()
    if symbols:
        asyncio.create_task(send(f"✅ *تم تحميل {len(symbols)} سهم من Finnhub (احتياطي)*"))
        return symbols
    
    asyncio.create_task(send("❌ *فشل تحميل الأسهم من جميع المصادر*"))
    return []

# ================= FETCH PRICES (POLYGON BATCH) =================
def fetch_all_prices():
    global PRICES_CACHE, PRICES_CACHE_TIME
    
    now = time.time()
    if PRICES_CACHE and (now - PRICES_CACHE_TIME < UPDATE_INTERVAL):
        return PRICES_CACHE
    
    prices = {}
    
    # 1. Polygon Aggregates (طلب واحد لكل الأسهم)
    if POLYGON_KEY:
        try:
            today = time.strftime("%Y-%m-%d")
            url = f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{today}?adjusted=true&apiKey={POLYGON_KEY}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("results", []):
                    symbol = item.get("T")
                    price = item.get("c")
                    if symbol and price:
                        prices[symbol] = price
                PRICES_CACHE = prices
                PRICES_CACHE_TIME = now
                print(f"Fetched {len(prices)} prices from Polygon")
                return prices
        except:
            pass
    
    # 2. Yahoo Finance (بدون مفتاح)
    symbols = load_symbols()
    for sym in symbols[:50]:
        try:
            ticker = yf.Ticker(sym)
            data = ticker.history(period="1d")
            if not data.empty:
                prices[sym] = data['Close'].iloc[-1]
        except:
            pass
    
    PRICES_CACHE = prices
    PRICES_CACHE_TIME = now
    return prices

# ================= SMART PRICE GETTER =================
def get_price_smart(symbol):
    return PRICES_CACHE.get(symbol, 0)

# ================= MOMENTUM =================
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
    if change >= 5: return 85
    elif change >= 3: return 70
    elif change >= 1: return 60
    elif change >= 0.5: return 50
    else: return 40

# ================= MAIN ENGINE =================
async def main():
    global DAILY_ALERTS

    await send("🔥 *الماسح الذكي - Polygon + Yahoo (بدون Finnhub)*")

    symbols = load_symbols()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم. تحقق من المفتاح.")
        return

    while True:
        try:
            all_prices = fetch_all_prices()
            if not all_prices:
                await asyncio.sleep(10)
                continue

            for sym in symbols[:500]:
                price = all_prices.get(sym, 0)
                if not price:
                    continue
                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                if detect(sym, price):
                    HOT_LIST.add(sym)
                await asyncio.sleep(SLEEP_BATCH)

            for sym in list(HOT_LIST):
                price = all_prices.get(sym, 0)
                if not price:
                    continue
                if can_alert(sym):
                    today = time.strftime("%Y-%m-%d")
                    if today not in DAILY_ALERTS:
                        DAILY_ALERTS[today] = {}
                    DAILY_ALERTS[today][sym] = DAILY_ALERTS[today].get(sym, 0) + 1

                    previous = PRICE_CACHE[sym]["previous"]
                    change = ((price - previous) / previous) * 100 if previous > 0 else 0
                    signal_score = get_signal_score(change)

                    msg = (
                        f"🚨 *إشارة زخم جديدة* 🚨\n\n"
                        f"📊 الرمز: `{sym}`\n"
                        f"💰 السعر: `${price:.2f}`\n"
                        f"📈 التغير القصير: `+{change:.2f}%`\n"
                        f"🔥 قوة الإشارة: `{signal_score}/100`\n"
                        f"🔢 التنبيه رقم: `{DAILY_ALERTS[today][sym]}`\n"
                        f"🕒 الوقت: `{time.strftime('%H:%M:%S')} EST`\n\n"
                        f"⚠️ للمتابعة فقط وليست توصية استثمارية"
                    )

                    await send(msg)
                    HOT_LIST.discard(sym)

                await asyncio.sleep(HOT_SLEEP)

            if len(PRICE_CACHE) > 10000:
                PRICE_CACHE.clear()

            await asyncio.sleep(5)

        except Exception as e:
            print(f"Main loop error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
