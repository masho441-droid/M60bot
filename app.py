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
MIN_MARKET_CAP = 10_000_000
MAX_MARKET_CAP = 300_000_000
SLEEP_BATCH = 0.1
HOT_SLEEP = 0.05
COOLDOWN = 300
UPDATE_INTERVAL = 60  # تحديث كل 60 ثانية

# ================= STATE =================
PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()
PRICES_CACHE = {}
PRICES_CACHE_TIME = 0
VOLUME_HISTORY = {}  # لتخزين الحجم لآخر 20 شمعة (5 دقائق)
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
                symbols_cache_time = time.time()
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
                symbols_cache_time = time.time()
                asyncio.create_task(send(f"✅ *تم تحميل {len(symbols_cache)} سهم من Finnhub*"))
                return symbols_cache
        except:
            pass
    
    return symbols_cache

# ================= FETCH 5-MINUTE AGGREGATES =================
def fetch_5min_aggs(symbol):
    """جلب بيانات آخر شمعتين (5 دقائق) من Polygon"""
    if not POLYGON_KEY:
        return None
    
    try:
        now = int(time.time() * 1000)
        five_min_ago = now - 300000  # 5 دقائق بالمللي ثانية
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{five_min_ago}/{now}?adjusted=true&sort=asc&limit=5&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=5)
        
        if r.status_code != 200:
            return None
        
        data = r.json()
        results = data.get("results", [])
        
        if len(results) < 2:
            return None
        
        # آخر شمعتين
        last = results[-1]
        prev = results[-2]
        
        return {
            "symbol": symbol,
            "price": last.get("c", 0),
            "volume": last.get("v", 0),
            "high": last.get("h", 0),
            "low": last.get("l", 0),
            "prev_price": prev.get("c", 0),
            "prev_volume": prev.get("v", 0),
            "timestamp": last.get("t", 0)
        }
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

# ================= SMART PRICE FETCHER (مع تخزين الحجم) =================
def get_price_with_volume(symbol):
    global VOLUME_HISTORY
    
    data = fetch_5min_aggs(symbol)
    if not data:
        return None
    
    # تحديث سجل الحجم (آخر 20 شمعة)
    if symbol not in VOLUME_HISTORY:
        VOLUME_HISTORY[symbol] = deque(maxlen=20)
    
    VOLUME_HISTORY[symbol].append(data["volume"])
    
    # حساب الحجم النسبي (RVOL)
    avg_volume = sum(VOLUME_HISTORY[symbol]) / len(VOLUME_HISTORY[symbol]) if VOLUME_HISTORY[symbol] else 1
    rvol = data["volume"] / avg_volume if avg_volume > 0 else 1
    
    # حساب التسارع (الزخم - الزخم السابق)
    prev_price = data["prev_price"]
    current_price = data["price"]
    if prev_price > 0:
        momentum = ((current_price - prev_price) / prev_price) * 100
    else:
        momentum = 0
    
    return {
        "symbol": symbol,
        "price": current_price,
        "volume": data["volume"],
        "rvol": rvol,
        "momentum": momentum,
        "timestamp": data["timestamp"]
    }

# ================= DETECT =================
def detect(symbol, price, momentum, rvol):
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {"previous": price, "current": price, "momentum": momentum}
        return False

    previous = PRICE_CACHE[symbol]["current"]
    PRICE_CACHE[symbol]["previous"] = previous
    PRICE_CACHE[symbol]["current"] = price
    PRICE_CACHE[symbol]["momentum"] = momentum

    if previous <= 0:
        return False

    change = ((price - previous) / previous) * 100
    
    # شروط الزخم: تغير ≥ 0.12% وحجم نسبي ≥ 1.2
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
