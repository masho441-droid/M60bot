import os
import asyncio
import logging
import pytz
import requests
from datetime import datetime, time as dt_time
from telegram import Bot

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

PREMARKET_MIN_VOLUME = 20000
PREMARKET_MIN_MOVE = 0.5
PREMARKET_MIN_REL_VOL = 0.8

last_alert = {}
alert_counters = {}
alert_history = {}

# ================= TIME =================
def ny():
    return datetime.now(pytz.timezone("America/New_York"))

def sa():
    return datetime.now(pytz.timezone("Asia/Riyadh"))

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

# ================= FINNHUB - جلب أكبر عدد ممكن =================
def fetch_max_stocks(is_premarket=False):
    """
    يجلب أكبر عدد ممكن من الأسهم خلال 55 طلب
    ويصفيهم حسب الفئة السعرية
    """
    print(f"📡 [Finnhub] جاري جلب أكبر عدد ممكن من الأسهم...")
    
    try:
        # جلب القائمة الكاملة
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        response = requests.get(url, timeout=30)
        
        if response.status_code != 200:
            print(f"⚠️ خطأ: {response.status_code}")
            return []
            
        all_symbols = response.json()
        
        if not isinstance(all_symbols, list):
            print("⚠️ بيانات غير متوقعة")
            return []
        
        print(f"📡 القائمة الكاملة: {len(all_symbols)} رمزاً")
        
        stocks = []
        request_count = 0
        max_requests = 55  # نترك 5 طلبات احتياطية
        
        # ===== نأخذ من القائمة بالترتيب بدون تقطيع =====
        for item in all_symbols:
            symbol = item.get("symbol")
            if not symbol:
                continue
            
            if request_count >= max_requests:
                print(f"⚠️ تم استهلاك {max_requests} طلب، نتوقف")
                break
            
            try:
                quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
                quote_res = requests.get(quote_url, timeout=10)
                request_count += 1
                
                if quote_res.status_code != 200:
                    continue
                    
                quote = quote_res.json()
                
                price = quote.get("c", 0)
                change = quote.get("dp", 0)
                volume = quote.get("v", 0)
                
                if price <= 0 or volume <= 0:
                    continue
                
                # ===== تصفية حسب الفئة السعرية (الأسهم الصغيرة) =====
                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                
                # حساب النشاط (السيولة)
                activity = volume * price
                
                stocks.append({
                    "ticker": symbol,
                    "close": price,
                    "change": change,
                    "volume": volume,
                    "activity": activity,
                    "momentum": abs(change) * volume
                })
                
            except Exception as e:
                logging.warning(f"⚠️ خطأ في {symbol}: {e}")
                continue
        
        print(f"📡 تم جمع {len(stocks)} سهماً من الفئة السعرية ${MIN_PRICE}-${MAX_PRICE}")
        return stocks
        
    except Exception as e:
        logging.error(f"Finnhub error: {e}")
        return []

# ================= YAHOO =================
def fetch_yahoo_stocks(symbols):
    """جلب بيانات Yahoo لرموز محددة"""
    if not symbols:
        return []
    
    print(f"📡 [Yahoo] جاري جلب البيانات لـ {len(symbols)} سهماً...")
    
    stocks = []
    
    for symbol in symbols[:10]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                continue
                
            data = response.json()
            meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
            
            price = meta.get('regularMarketPrice', 0)
            volume = meta.get('regularMarketVolume', 0)
            
            if price <= 0 or volume <= 0:
                continue
            
            prev_close = meta.get('regularMarketPreviousClose', price)
            change = ((price - prev_close) / prev_close) * 100 if prev_close else 0
            
            stocks.append({
                "ticker": symbol,
                "close": price,
                "change": change,
                "volume": volume
            })
            
        except Exception as e:
            continue
    
    print(f"📡 [Yahoo] تم جلب {len(stocks)} سهماً")
    return stocks

# ================= MERGE =================
def merge_stocks(finnhub_stocks, yahoo_stocks):
    """دمج الأسهم"""
    all_stocks = finnhub_stocks + yahoo_stocks
    
    seen = set()
    unique = []
    for s in all_stocks:
        ticker = s.get("ticker")
        if ticker and ticker not in seen:
            seen.add(ticker)
            unique.append(s)
    
    return unique

# ================= VOLUME RATIO =================
def calculate_rel_vol(volume, symbol):
    avg_volume = 50000
    return volume / avg_volume if avg_volume > 0 else 1.0

# ================= FILTER =================
def valid(s, is_premarket=False):
    try:
        price = float(s.get("close") or 0)
        change = float(s.get("change") or 0)
        vol = float(s.get("volume") or 0)

        if price < MIN_PRICE or price > MAX_PRICE:
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

    for s in stocks:
        if not valid(s, is_premarket):
            continue

        sym = s.get("ticker")
        price = float(s.get("close") or 0)
        volume = float(s.get("volume") or 0)
        change = float(s.get("change") or 0)

        rel_vol = calculate_rel_vol(volume, sym)

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
    print(f"💰 الفئة: ${MIN_PRICE} - ${MAX_PRICE}")

    await send("🔥 *M60 Hunter - صيد الأسهم الصغيرة*")

    while True:
        current_session = get_session()
        print(f"\n🔄 دورة جديدة - {current_session}")
        
        if current_session == "closed":
            await asyncio.sleep(300)
            continue

        # ===== جلب أكبر عدد ممكن من الأسهم =====
        is_premarket = (current_session == "premarket")
        all_stocks = fetch_max_stocks(is_premarket)
        
        if not all_stocks:
            print("⚠️ لا توجد أسهم، إعادة المحاولة...")
            await asyncio.sleep(30)
            continue

        # ===== ترتيب حسب النشاط (السيولة) =====
        all_stocks.sort(key=lambda x: x["activity"], reverse=True)
        
        # ===== أخذ أعلى 100 سهم نشاطاً =====
        top_100 = all_stocks[:100]
        print(f"📡 تم اختيار أعلى 100 سهم نشاطاً")
        
        # ===== ترتيب الـ 100 حسب الزخم =====
        top_100.sort(key=lambda x: x["momentum"], reverse=True)
        
        # ===== أخذ أعلى 40 سهم زخم =====
        top_40 = top_100[:40]
        print(f"📡 تم اختيار أعلى 40 سهم زخماً")
        
        # ===== إضافة Yahoo في التداول العادي =====
        if not is_premarket:
            yahoo_symbols = [s["ticker"] for s in top_40[:10]]
            yahoo_stocks = fetch_yahoo_stocks(yahoo_symbols)
            top_40 = merge_stocks(top_40, yahoo_stocks)
        
        # ===== تطبيق الشروط =====
        signals = detect(top_40, is_premarket)
        
        print(f"✅ signals: {len(signals)}")
        
        for s in signals:
            await send_alert(*s)
            await asyncio.sleep(1)
        
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
