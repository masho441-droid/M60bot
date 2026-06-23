import os
import asyncio
import logging
import pytz
import requests
from datetime import datetime, time as dt_time
from telegram import Bot
import time
from flask import Flask
from threading import Thread
import traceback

# ================= FAKE WEB SERVER (for Render) =================
web_app = Flask('')

@web_app.route('/')
def home():
    return "M60bot is running!"

def run_web_server():
    web_app.run(host='0.0.0.0', port=10000)

# ================= START WEB SERVER IN BACKGROUND =================
Thread(target=run_web_server, daemon=True).start()

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# ================= ENV =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing Telegram config")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_MOVE = 1.0
MIN_VOLUME = 50000
COOLDOWN = 120
MIN_REL_VOL = 1.2
MIN_MARKET_CAP = 10_000_000   # 10 مليون
MAX_MARKET_CAP = 150_000_000  # 150 مليون

PREMARKET_MIN_VOLUME = 20000
PREMARKET_MIN_MOVE = 0.5
PREMARKET_MIN_REL_VOL = 0.8

last_alert = {}
alert_counters = {}
alert_history = {}
symbols_cache = None
last_cache_update = 0

# ================= TIME =================
def ny():
    return datetime.now(pytz.timezone("America/New_York"))

def get_session():
    t = ny().time()
    if dt_time(4, 0) <= t < dt_time(9, 30):
        return "premarket"
    if dt_time(9, 30) <= t < dt_time(16, 0):
        return "regular"
    if dt_time(16, 0) <= t < dt_time(20, 0):
        return "afterhours"
    return "closed"

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

# ================= GET SYMBOLS LIST (CACHED) =================
def get_symbols():
    global symbols_cache, last_cache_update
    now = time.time()
    if symbols_cache and (now - last_cache_update) < 3600:
        return symbols_cache
    
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return symbols_cache or []
        data = response.json()
        if isinstance(data, list):
            symbols_cache = data
            last_cache_update = now
            logging.info(f"✅ تم تحديث قائمة الرموز: {len(symbols_cache)} رمزاً")
            return symbols_cache
        return []
    except Exception as e:
        logging.error(f"خطأ في جلب القائمة: {e}")
        return symbols_cache or []

# ================= GET MARKET CAP + QUOTE (طلب واحد) =================
def get_stock_data(symbol):
    """تجلب القيمة السوقية والسعر والحجم في طلب واحد"""
    try:
        # استخدام profile2 للحصول على القيمة السوقية
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_KEY}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 429:
            logging.warning(f"⚠️ [Finnhub] رمز {symbol} أعاد كود 429 (تجاوز الحد)")
            return None
            
        if response.status_code != 200:
            return None
            
        data = response.json()
        market_cap = data.get("marketCapitalization")
        
        if not market_cap:
            return None
            
        market_cap = float(market_cap) * 1_000_000
        
        # جلب السعر والحجم من quote
        quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        quote_res = requests.get(quote_url, timeout=10)
        
        if quote_res.status_code == 429:
            logging.warning(f"⚠️ [Finnhub] رمز {symbol} أعاد كود 429 (تجاوز الحد)")
            return None
            
        if quote_res.status_code != 200:
            return None
            
        quote = quote_res.json()
        price = quote.get("c", 0)
        change = quote.get("dp", 0)
        volume = quote.get("v", 0)
        
        if price <= 0 or volume <= 0:
            return None
            
        return {
            "ticker": symbol,
            "close": price,
            "change": change,
            "volume": volume,
            "market_cap": market_cap
        }
        
    except Exception as e:
        return None

# ================= VOLUME RATIO =================
def calculate_rel_vol(volume):
    avg_volume = 50000
    return volume / avg_volume if avg_volume > 0 else 1.0

# ================= FILTER =================
def valid(stock, is_premarket=False):
    try:
        price = float(stock.get("close") or 0)
        change = float(stock.get("change") or 0)
        vol = float(stock.get("volume") or 0)
        market_cap = float(stock.get("market_cap") or 0)

        if price < MIN_PRICE or price > MAX_PRICE:
            return False
        if market_cap < MIN_MARKET_CAP or market_cap > MAX_MARKET_CAP:
            return False
        if is_premarket:
            if vol < PREMARKET_MIN_VOLUME or change < PREMARKET_MIN_MOVE:
                return False
        else:
            if vol < MIN_VOLUME or change < MIN_MOVE:
                return False
        return True
    except:
        return False

# ================= ENGINE =================
def detect(stocks, is_premarket=False):
    alerts = []

    for stock in stocks:
        if not valid(stock, is_premarket):
            continue

        sym = stock.get("ticker")
        price = float(stock.get("close") or 0)
        volume = float(stock.get("volume") or 0)
        change = float(stock.get("change") or 0)

        rel_vol = calculate_rel_vol(volume)

        if is_premarket:
            if rel_vol < PREMARKET_MIN_REL_VOL:
                continue
        else:
            if rel_vol < MIN_REL_VOL:
                continue

        now = ny().timestamp()
        if now - last_alert.get(sym, 0) < COOLDOWN:
            continue

        last_alert[sym] = now
        alert_counters[sym] = alert_counters.get(sym, 0) + 1

        target1 = price * 1.05
        target2 = price * 1.10
        target3 = price * 1.15
        stop_loss = price * 0.95

        if change > 3.0 and volume > 500000:
            strength = "💥 قوية جداً"
        elif change > 2.0 and volume > 200000:
            strength = "🚀 قوية"
        else:
            strength = "📈 متوسطة"

        alerts.append((sym, price, change, rel_vol, 1.0, alert_counters[sym], target1, target2, target3, stop_loss, strength))

    return alerts

# ================= ALERT FORMAT =================
async def send_alert(sym, price, move, rel_vol, mom_acc, alert_num, t1, t2, t3, sl, strength):
    now = ny().strftime("%H:%M:%S")
    
    if move > 3.0 and rel_vol > 2.0:
        move_type = "🚀 انفجار قوي"
    elif move > 2.0 and rel_vol > 1.5:
        move_type = "📈 اختراق إيجابي"
    else:
        move_type = "📈 تحرك"

    msg = (
        f"📊 *{sym} — {now}* 📊\n\n"
        f"🔹 *السعر:* `${price:.2f}`\n"
        f"🔹 *الارتفاع:* `+{move:.2f}%`\n"
        f"🔹 *الحجم النسبي:* `{rel_vol:.1f}x`\n"
        f"🔹 *التنبيه:* `{alert_num} مرة`\n\n"
        f"🎯 *الأهداف:*\n"
        f"  • مقاومة 1: `{t1:.3f}`\n"
        f"  • مقاومة 2: `{t2:.3f}`\n"
        f"  • دعم: `{sl:.3f}`\n\n"
        f"📌 *توصية:* {strength}"
    )
    await send(msg)

# ================= MAIN =================
async def main():
    print(f"🕒 الوقت: {ny().strftime('%H:%M:%S')}")
    print(f"📌 الجلسة: {get_session()}")
    print(f"💰 الفئة السعرية: ${MIN_PRICE} - ${MAX_PRICE}")
    print(f"📊 القيمة السوقية: ${MIN_MARKET_CAP/1_000_000:.0f}M - ${MAX_MARKET_CAP/1_000_000:.0f}M")
    print(f"🔍 المصدر: Finnhub (مع إدارة ذكية للطلبات)")

    await send("📊 *M60 Hunter V11 - Finnhub (محسن)*")

    while True:
        current_session = get_session()
        print(f"\n🔄 دورة جديدة - {current_session}")
        
        # ===== جلب القائمة =====
        all_symbols = get_symbols()
        if not all_symbols:
            print("⚠️ لا توجد رموز، إعادة المحاولة...")
            await asyncio.sleep(30)
            continue

        # ===== نأخذ 100 سهم فقط لكل دورة =====
        symbols_to_check = all_symbols[:100]
        print(f"📡 جاري تدقيق {len(symbols_to_check)} رمزاً...")
        
        filtered_stocks = []
        request_count = 0
        
        for item in symbols_to_check:
            symbol = item.get("symbol")
            if not symbol:
                continue
            
            try:
                # ===== تأخير 1.5 ثانية بين الطلبات =====
                await asyncio.sleep(1.5)
                
                data = get_stock_data(symbol)
                request_count += 1
                
                if data:
                    filtered_stocks.append(data)
                    print(f"✅ {symbol}: ${data['close']:.2f}, {data['change']:.2f}%, حجم: {data['volume']:,}, قيمة: ${data['market_cap']/1_000_000:.1f}M")
                
                # ===== كل 55 طلب، ننتظر 10 ثوانٍ إضافية =====
                if request_count % 55 == 0:
                    print(f"⏳ تم إرسال {request_count} طلب، ننتظر 10 ثوانٍ...")
                    await asyncio.sleep(10)
                    
            except Exception as e:
                logging.error(f"⚠️ خطأ في {symbol}: {e}")
                continue
        
        print(f"📡 تم العثور على {len(filtered_stocks)} سهماً ضمن الفئة المستهدفة")
        
        if not filtered_stocks:
            print("⏳ لا توجد أسهم مطابقة، ننتظر 30 ثانية...")
            await asyncio.sleep(30)
            continue
        
        # ===== ترتيب حسب النشاط والزخم =====
        filtered_stocks.sort(key=lambda x: (x["volume"] * x["close"]), reverse=True)
        top_40 = filtered_stocks[:40]
        
        # ===== تطبيق الشروط =====
        is_premarket = (current_session == "premarket" or current_session == "afterhours")
        signals = detect(top_40, is_premarket)
        
        print(f"✅ signals: {len(signals)}")
        
        for s in signals:
            await send_alert(*s)
            await asyncio.sleep(1)
        
        # ===== ننتظر 30 ثانية قبل الدورة التالية =====
        print(f"⏳ انتظار 30 ثانية...")
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
