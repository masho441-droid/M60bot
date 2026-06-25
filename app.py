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
    return "Smart Scanner is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")
POLYGON_KEY = os.getenv("POLYGON_KEY")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing TELEGRAM_TOKEN or CHAT_ID")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_MARKET_CAP = 10_000_000
MAX_MARKET_CAP = 300_000_000
SLEEP_BATCH = 0.2
HOT_SLEEP = 0.05
COOLDOWN = 300
UPDATE_INTERVAL = 60  # تحديث البيانات كل 60 ثانية

# ================= CACHE =================
symbols_cache = []
symbols_cache_time = 0
prices_cache = {}
prices_cache_time = 0
PRICE_HISTORY = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= LOAD SYMBOLS (مرة كل 6 ساعات) =================
def load_symbols():
    global symbols_cache, symbols_cache_time
    
    now = time.time()
    if symbols_cache and (now - symbols_cache_time < 21600):  # 6 ساعات
        return symbols_cache
    
    if not FINNHUB_KEY:
        return []
    
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return symbols_cache
        data = r.json()
        symbols_cache = [x["symbol"] for x in data if "symbol" in x]
        symbols_cache_time = now
        asyncio.create_task(send(f"✅ *تم تحميل {len(symbols_cache)} سهم من Finnhub*"))
        return symbols_cache
    except:
        return symbols_cache

# ================= FETCH ALL PRICES (طلب واحد مجمع) =================
def fetch_all_prices():
    global prices_cache, prices_cache_time
    
    now = time.time()
    if prices_cache and (now - prices_cache_time < UPDATE_INTERVAL):
        return prices_cache
    
    prices = {}
    
    # 1. محاولة Polygon (طلب واحد مجمع)
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
                prices_cache = prices
                prices_cache_time = now
                print(f"Fetched {len(prices)} prices from Polygon (1 request)")
                return prices
        except:
            pass
    
    # 2. إذا فشل Polygon، استخدم Finnhub (لكل سهم على حدة - استهلاك أعلى)
    if FINNHUB_KEY:
        symbols = load_symbols()
        count = 0
        for sym in symbols[:100]:  # حد أقصى 100 سهم لتجنب استهلاك كبير
            try:
                url = f"https://finnhub.io/api/v1/quote?symbol={sym}&token={FINNHUB_KEY}"
                r = requests.get(url, timeout=3)
                if r.status_code == 200:
                    price = r.json().get("c", 0)
                    if price > 0:
                        prices[sym] = price
                        count += 1
                await asyncio.sleep(0.1)  # تجنب تجاوز الحد
            except:
                pass
        print(f"Fetched {count} prices from Finnhub (fallback)")
    
    prices_cache = prices
    prices_cache_time = now
    return prices

# ================= SMART PRICE GETTER (من الكاش) =================
def get_price_smart(symbol):
    return prices_cache.get(symbol, 0)

# ================= MOMENTUM DETECTOR =================
def detect(symbol, price):
    if symbol not in PRICE_HISTORY:
        PRICE_HISTORY[symbol] = {"previous": price, "current": price}
        return False

    previous = PRICE_HISTORY[symbol]["current"]
    PRICE_HISTORY[symbol]["previous"] = previous
    PRICE_HISTORY[symbol]["current"] = price

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

    await send("🔥 *الماسح الذكي - دمج المصادر مع تخزين مؤقت*")

    symbols = load_symbols()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم. تحقق من المفتاح.")
        return

    while True:
        try:
            # 1. جلب جميع الأسعار دفعة واحدة (طلب واحد)
            all_prices = fetch_all_prices()
            
            if not all_prices:
                await asyncio.sleep(10)
                continue

            # 2. فحص جميع الأسهم
            for sym in symbols[:500]:  # حد أقصى 500 سهم لكل دورة
                price = all_prices.get(sym, 0)
                if not price:
                    continue

                if price < MIN_PRICE or price > MAX_PRICE:
                    continue

                if detect(sym, price):
                    HOT_LIST.add(sym)

                await asyncio.sleep(SLEEP_BATCH)

            # 3. فحص الأسهم الساخنة
            for sym in list(HOT_LIST):
                price = all_prices.get(sym, 0)
                if not price:
                    continue

                if can_alert(sym):
                    today = time.strftime("%Y-%m-%d")
                    if today not in DAILY_ALERTS:
                        DAILY_ALERTS[today] = {}
                    DAILY_ALERTS[today][sym] = DAILY_ALERTS[today].get(sym, 0) + 1

                    previous = PRICE_HISTORY[sym]["previous"]
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

            # منع تضخم الذاكرة
            if len(PRICE_HISTORY) > 10000:
                PRICE_HISTORY.clear()

            await asyncio.sleep(5)  # انتظار قصير بين الدورات

        except Exception as e:
            print(f"Main loop error: {e}")
            await asyncio.sleep(10)

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
