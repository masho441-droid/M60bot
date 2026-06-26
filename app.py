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
    return "iTick Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ITICK_TOKEN = os.getenv("ITICK_TOKEN")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing TELEGRAM_TOKEN or CHAT_ID")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_VOLUME = 100000
SLEEP_BETWEEN = 0.15
COOLDOWN = 300
UPDATE_INTERVAL = 60
BATCH_SIZE = 100

PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()
PRICES_CACHE = {}
PRICES_CACHE_TIME = 0
symbols_cache = []
symbols_cache_time = 0
symbols_loaded = False

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= SOURCE 1: ITICK =================
def fetch_symbols_itick():
    """جلب قائمة الأسهم من iTick (نقطة النهاية الصحيحة)"""
    if not ITICK_TOKEN:
        return None
    try:
        url = "https://api.itick.org/symbol/list"
        headers = {"accept": "application/json", "token": ITICK_TOKEN}
        params = {"type": "stock", "region": "US", "limit": 1000}
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 0:
                symbols = []
                for item in data.get("data", []):
                    symbol = item.get("symbol") or item.get("code")
                    if symbol:
                        symbols.append(symbol)
                if symbols:
                    print(f"Loaded {len(symbols)} symbols from iTick")
                    return symbols
        print(f"iTick symbol error: {r.status_code}")
    except Exception as e:
        print(f"iTick exception: {e}")
    return None

def fetch_prices_itick(symbols):
    """جلب بيانات الأسعار من iTick (دفعات)"""
    if not ITICK_TOKEN or not symbols:
        return {}
    
    prices = {}
    url = "https://api.itick.org/stock/quotes"
    headers = {"accept": "application/json", "token": ITICK_TOKEN}
    
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i+BATCH_SIZE]
        try:
            params = {"region": "US", "codes": ",".join(batch)}
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == 0:
                    quotes = data.get("data", {})
                    for symbol, info in quotes.items():
                        price = info.get("ld", 0)
                        volume = info.get("v", 0)
                        if price > 0:
                            prices[symbol] = {"price": price, "volume": volume}
            time.sleep(0.3)
        except Exception as e:
            print(f"iTick batch error: {e}")
    return prices

# ================= SOURCE 2: FINNHUB (احتياطي) =================
def fetch_symbols_finnhub():
    if not FINNHUB_KEY:
        return None
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            symbols = [x["symbol"] for x in r.json() if "symbol" in x]
            print(f"Loaded {len(symbols)} symbols from Finnhub")
            return symbols
    except:
        pass
    return None

def fetch_prices_finnhub(symbols):
    prices = {}
    for sym in symbols[:100]:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                data = r.json()
                price = data.get("c", 0)
                volume = data.get("v", 0)
                if price > 0:
                    prices[sym] = {"price": price, "volume": volume}
            time.sleep(0.1)
        except:
            pass
    return prices

# ================= SMART LOADER =================
def load_symbols():
    global symbols_cache, symbols_cache_time, symbols_loaded
    
    if symbols_loaded and symbols_cache:
        return symbols_cache
    
    symbols = fetch_symbols_itick()
    if symbols:
        symbols_loaded = True
        symbols_cache = symbols
        symbols_cache_time = time.time()
        asyncio.create_task(send(f"✅ *تم تحميل {len(symbols)} سهم من iTick*"))
        return symbols
    
    symbols = fetch_symbols_finnhub()
    if symbols:
        symbols_loaded = True
        symbols_cache = symbols
        symbols_cache_time = time.time()
        asyncio.create_task(send(f"✅ *تم تحميل {len(symbols)} سهم من Finnhub (احتياطي)*"))
        return symbols
    
    return []

# ================= SMART PRICE FETCHER =================
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
    
    prices = fetch_prices_finnhub(symbols)
    if prices:
        PRICES_CACHE = prices
        PRICES_CACHE_TIME = now
        return prices
    
    return {}

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

    await send("🔥 *الماسح الذكي - iTick + Finnhub*")

    symbols = load_symbols()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم. تحقق من المفاتيح.")
        return

    while True:
        try:
            all_prices = fetch_prices(symbols)
            if not all_prices:
                await asyncio.sleep(10)
                continue

            for sym in symbols[:500]:
                data = all_prices.get(sym)
                if not data:
                    continue
                price = data["price"]
                volume = data.get("volume", 0)

                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                if volume < MIN_VOLUME:
                    continue

                if detect(sym, price):
                    HOT_LIST.add(sym)

                await asyncio.sleep(SLEEP_BETWEEN)

            for sym in list(HOT_LIST):
                data = all_prices.get(sym)
                if not data:
                    continue
                price = data["price"]

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

                await asyncio.sleep(SLEEP_BETWEEN)

            if len(PRICE_CACHE) > 10000:
                PRICE_CACHE.clear()

            await asyncio.sleep(5)

        except Exception as e:
            print(f"Main loop error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
