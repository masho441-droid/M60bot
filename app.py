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

if not TOKEN or not CHAT_ID or not ITICK_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN, CHAT_ID, or ITICK_TOKEN")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10
MIN_VOLUME = 100000  # الحد الأدنى للحجم (للتأكد من وجود سيولة)
SLEEP_BETWEEN = 0.2
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

# ================= FETCH SYMBOLS (iTick) =================
def fetch_symbols():
    """جلب قائمة الأسهم النشطة من iTick (أول 1000 سهم)"""
    try:
        url = "https://api.itick.org/stock/symbols"
        headers = {"accept": "application/json", "token": ITICK_TOKEN}
        params = {"region": "US", "limit": 1000}
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 0:
                symbols = [item["symbol"] for item in data.get("data", []) if "symbol" in item]
                print(f"Loaded {len(symbols)} symbols from iTick")
                return symbols
        print(f"iTick symbol error: {r.status_code}")
    except Exception as e:
        print(f"iTick symbol exception: {e}")
    return []

# ================= FETCH ALL PRICES (iTick) =================
def fetch_all_prices(symbols):
    """جلب بيانات جميع الأسهم في طلب واحد (Quotes)"""
    global PRICES_CACHE, PRICES_CACHE_TIME
    
    now = time.time()
    if PRICES_CACHE and (now - PRICES_CACHE_TIME < UPDATE_INTERVAL):
        return PRICES_CACHE
    
    prices = {}
    
    if not symbols:
        return prices
    
    # تقسيم القائمة إلى دفعات (لتجنب تجاوز الحد)
    batch_size = 100
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        try:
            url = "https://api.itick.org/stock/quotes"
            headers = {"accept": "application/json", "token": ITICK_TOKEN}
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
            await asyncio.sleep(0.5)  # لتجنب تجاوز الحد
        except Exception as e:
            print(f"Batch error: {e}")
    
    PRICES_CACHE = prices
    PRICES_CACHE_TIME = now
    print(f"Fetched {len(prices)} prices from iTick")
    return prices

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
    if change >= 5: return 85
    elif change >= 3: return 70
    elif change >= 1: return 60
    elif change >= 0.5: return 50
    else: return 40

# ================= MAIN ENGINE =================
async def main():
    global DAILY_ALERTS

    await send("🔥 *الماسح الذكي - iTick*")

    symbols = fetch_symbols()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم. تحقق من المفتاح.")
        return

    await send(f"✅ *تم تحميل {len(symbols)} سهم من iTick*")

    while True:
        try:
            all_prices = fetch_all_prices(symbols)
            if not all_prices:
                await asyncio.sleep(10)
                continue

            for sym in symbols[:500]:
                data = all_prices.get(sym)
                if not data:
                    continue
                price = data["price"]
                volume = data["volume"]

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
