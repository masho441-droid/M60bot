import os
import asyncio
import time
import requests
import yfinance as yf
from telegram import Bot
from collections import deque

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
SLEEP_BATCH = 0.1
HOT_SLEEP = 0.05
COOLDOWN = 300
UPDATE_INTERVAL = 60

# ================= STATE =================
PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()
VOLUME_HISTORY = {}
symbols_cache = []
symbols_cache_time = 0
symbols_loaded = False

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= LOAD SYMBOLS =================
def load_symbols():
    global symbols_cache, symbols_cache_time, symbols_loaded
    
    if symbols_loaded and symbols_cache:
        return symbols_cache
    
    if POLYGON_KEY:
        try:
            url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&limit=1000&apiKey={POLYGON_KEY}"
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                symbols_cache = [x["ticker"] for x in data.get("results", []) if "ticker" in x]
                symbols_loaded = True
                asyncio.create_task(send(f"✅ *تم تحميل {len(symbols_cache)} سهم من Polygon*"))
                return symbols_cache
        except:
            pass
    
    if FINNHUB_KEY:
        try:
            url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                symbols_cache = [x["symbol"] for x in data if "symbol" in x]
                symbols_loaded = True
                asyncio.create_task(send(f"✅ *تم تحميل {len(symbols_cache)} سهم من Finnhub*"))
                return symbols_cache
        except:
            pass
    
    return symbols_cache

# ================= FETCH 5-MINUTE AGGREGATES =================
def fetch_5min_aggs(symbol):
    if not POLYGON_KEY:
        return None
    
    try:
        now = int(time.time() * 1000)
        five_min_ago = now - 300000
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{five_min_ago}/{now}?adjusted=true&sort=asc&limit=5&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=5)
        
        if r.status_code != 200:
            return None
        
        data = r.json()
        results = data.get("results", [])
        
        if len(results) < 2:
            return None
        
        last = results[-1]
        prev = results[-2]
        
        return {
            "symbol": symbol,
            "price": last.get("c", 0),
            "volume": last.get("v", 0),
            "prev_price": prev.get("c", 0),
            "prev_volume": prev.get("v", 0),
        }
    except:
        return None

# ================= SMART PRICE FETCHER =================
def get_price_with_volume(symbol):
    global VOLUME_HISTORY
    
    data = fetch_5min_aggs(symbol)
    if not data:
        return None
    
    # تجاهل الأسهم ذات السعر صفر (غير نشطة)
    if data["price"] <= 0:
        return None
    
    if symbol not in VOLUME_HISTORY:
        VOLUME_HISTORY[symbol] = deque(maxlen=20)
    
    VOLUME_HISTORY[symbol].append(data["volume"])
    
    avg_volume = sum(VOLUME_HISTORY[symbol]) / len(VOLUME_HISTORY[symbol]) if VOLUME_HISTORY[symbol] else 1
    rvol = data["volume"] / avg_volume if avg_volume > 0 else 1
    
    if data["prev_price"] > 0:
        momentum = ((data["price"] - data["prev_price"]) / data["prev_price"]) * 100
    else:
        momentum = 0
    
    return {
        "symbol": symbol,
        "price": data["price"],
        "volume": data["volume"],
        "rvol": rvol,
        "momentum": momentum,
    }

# ================= DETECT =================
def detect(symbol, price, momentum, rvol):
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {"previous": price, "current": price}
        return False

    previous = PRICE_CACHE[symbol]["current"]
    PRICE_CACHE[symbol]["previous"] = previous
    PRICE_CACHE[symbol]["current"] = price

    if previous <= 0:
        return False

    change = ((price - previous) / previous) * 100
    
    if change >= 0.12 and rvol >= 1.2:
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

# ================= SIGNAL SCORE =================
def get_signal_score(change, rvol):
    score = 0
    if change >= 5:
        score += 40
    elif change >= 3:
        score += 30
    elif change >= 1:
        score += 20
    elif change >= 0.5:
        score += 10
    
    if rvol >= 3:
        score += 30
    elif rvol >= 2:
        score += 20
    elif rvol >= 1.5:
        score += 10
    
    return min(score, 100)

# ================= MAIN ENGINE =================
async def main():
    global DAILY_ALERTS

    await send("🔥 *الماسح الذكي - 5 دقائق + تسارع + RVOL*")

    symbols = load_symbols()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم.")
        return

    while True:
        try:
            print(f"فحص {len(symbols[:500])} سهماً...")
            
            for sym in symbols[:500]:
                data = get_price_with_volume(sym)
                if not data:
                    continue
                
                price = data["price"]
                momentum = data["momentum"]
                rvol = data["rvol"]
                
                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                
                if detect(sym, price, momentum, rvol):
                    HOT_LIST.add(sym)
                
                await asyncio.sleep(SLEEP_BATCH)

            for sym in list(HOT_LIST):
                data = get_price_with_volume(sym)
                if not data:
                    continue
                
                price = data["price"]
                momentum = data["momentum"]
                rvol = data["rvol"]
                
                if can_alert(sym):
                    today = time.strftime("%Y-%m-%d")
                    if today not in DAILY_ALERTS:
                        DAILY_ALERTS[today] = {}
                    DAILY_ALERTS[today][sym] = DAILY_ALERTS[today].get(sym, 0) + 1

                    change = ((price - PRICE_CACHE[sym]["previous"]) / PRICE_CACHE[sym]["previous"]) * 100 if PRICE_CACHE[sym]["previous"] > 0 else 0
                    signal_score = get_signal_score(change, rvol)

                    msg = (
                        f"🚨 *إشارة زخم جديدة* 🚨\n\n"
                        f"📊 الرمز: `{sym}`\n"
                        f"💰 السعر: `${price:.2f}`\n"
                        f"📈 الزخم: `{change:+.2f}%`\n"
                        f"📊 RVOL: `{rvol:.1f}x`\n"
                        f"🚀 التسارع: `{momentum:+.2f}%`\n"
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

            await asyncio.sleep(UPDATE_INTERVAL)

        except Exception as e:
            print(f"Main loop error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
