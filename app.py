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
UPDATE_INTERVAL = 60  # التحديث كل 60 ثانية (بدلاً من ساعة)

PRICE_CACHE = {}
LAST_ALERT = {}
DAILY_ALERTS = {}
HOT_LIST = set()
LAST_UPDATE = 0
CACHED_PRICES = {}

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except:
        pass

# ================= LOAD SYMBOLS =================
def load_symbols_with_filters():
    """جلب الأسهم مع فلتر آمن للقيمة السوقية"""
    try:
        url = f"https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&limit=1000&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print(f"خطأ في جلب الأسهم: {r.status_code}")
            return []
        data = r.json()
        filtered = []
        for ticker in data.get("results", []):
            symbol = ticker.get("ticker")
            market_cap = ticker.get("market_cap")
            if not symbol:
                continue
            # فلترة آمنة: تجاهل الأسهم التي لا تملك قيمة سوقية
            if market_cap is None:
                continue
            if market_cap < MIN_MARKET_CAP or market_cap > MAX_MARKET_CAP:
                continue
            filtered.append(symbol)
        
        # إرسال تقرير بعدد الأسهم التي اجتازت الفلتر
        asyncio.create_task(send(
            f"✅ *تم تحميل {len(filtered)} سهم*\n"
            f"السعر: ${MIN_PRICE} - ${MAX_PRICE}\n"
            f"القيمة السوقية: {MIN_MARKET_CAP/1e6:.0f}M - {MAX_MARKET_CAP/1e6:.0f}M"
        ))
        
        print(f"Loaded {len(filtered)} symbols after filtering")
        return filtered
    except Exception as e:
        print(f"خطأ: {e}")
        return []

# ================= FETCH PRICES =================
def fetch_prices():
    """جلب بيانات الأسعار (مع تخزين مؤقت)"""
    global LAST_UPDATE, CACHED_PRICES
    
    now = time.time()
    
    # تحديث كل 60 ثانية
    if now - LAST_UPDATE < UPDATE_INTERVAL and CACHED_PRICES:
        return CACHED_PRICES
    
    today = time.strftime("%Y-%m-%d")
    
    try:
        url = f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{today}?adjusted=true&apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=30)
        
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            prices = {item["T"]: item["c"] for item in results if "c" in item}
            CACHED_PRICES = prices
            LAST_UPDATE = now
            print(f"Fetched {len(prices)} prices")
            return prices
        else:
            print(f"خطأ في جلب الأسعار: {r.status_code}")
            return CACHED_PRICES
            
    except Exception as e:
        print(f"خطأ في جلب الأسعار: {e}")
        return CACHED_PRICES

# ================= MOMENTUM (معدل) =================
def detect(symbol, price):
    """كشف الزخم مع تخزين السعر السابق بشكل صحيح"""
    if symbol not in PRICE_CACHE:
        PRICE_CACHE[symbol] = {
            "previous": price,
            "current": price
        }
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

# ================= SIGNAL SCORE (بدلاً من نسبة النجاح) =================
def get_signal_score(change):
    """حساب قوة الإشارة بناءً على الزخم"""
    if change >= 5:
        return 85
    elif change >= 3:
        return 70
    elif change >= 1:
        return 60
    elif change >= 0.5:
        return 50
    else:
        return 40

# ================= MAIN ENGINE =================
async def main():
    global DAILY_ALERTS

    await send("🔥 *الماسح الشامل (Polygon) - النسخة المحسنة*")

    symbols = load_symbols_with_filters()
    if not symbols:
        await send("⚠️ لم يتم العثور على أسهم. تحقق من المفتاح أو الإعدادات.")
        return

    while True:
        try:
            # 1. جلب البيانات
            all_prices = fetch_prices()
            if not all_prices:
                await asyncio.sleep(10)
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
                    
                    # حساب الزخم الصحيح
                    previous = PRICE_CACHE[sym]["previous"]
                    change = ((price - previous) / previous) * 100 if previous > 0 else 0
                    signal_score = get_signal_score(change)

                    msg = (
                        f"🚨 *إشارة زخم جديدة* 🚨\n\n"
                        f"📊 الرمز: `{sym}`\n"
                        f"💰 السعر: `${price:.2f}`\n"
                        f"📈 التغير القصير: `+{change:.2f}%`\n"
                        f"🔥 قوة الإشارة: `{signal_score}/100`\n"
                        f"🔢 التنبيه رقم: `{alert_count}`\n"
                        f"🕒 الوقت: `{time.strftime('%H:%M:%S')} EST`\n\n"
                        f"⚠️ للمتابعة فقط وليست توصية استثمارية"
                    )

                    await send(msg)
                    
                    # تنظيف HOT_LIST بعد التنبيه
                    HOT_LIST.discard(sym)

                await asyncio.sleep(HOT_SLEEP)

            # منع تضخم الذاكرة
            if len(PRICE_CACHE) > 10000:
                PRICE_CACHE.clear()
                print("Cleared PRICE_CACHE to prevent memory bloat")

            await asyncio.sleep(1)

        except Exception as e:
            print(f"Main loop error: {e}")
            await asyncio.sleep(10)

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
