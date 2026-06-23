import os
import asyncio
import logging
import pytz
import yfinance as yf
from datetime import datetime, time as dt_time
from telegram import Bot
import time
from flask import Flask
from threading import Thread

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
FINNHUB_KEY = os.getenv("FINNHUB_KEY")  # للاستخدام الاحتياطي فقط

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

# إعدادات منفصلة للبري ماركت والآفتر ماركت (أخف)
PREMARKET_MIN_VOLUME = 20000
PREMARKET_MIN_MOVE = 0.5
PREMARKET_MIN_REL_VOL = 0.8

last_alert = {}
alert_counters = {}
alert_history = {}

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

# ================= GET STOCK DATA (Yahoo Finance - yfinance) =================
def get_stock_data(symbol):
    """تجلب جميع بيانات السهم من Yahoo Finance في طلب واحد"""
    try:
        ticker = yf.Ticker(symbol)
        
        # جلب المعلومات الأساسية
        info = ticker.info
        
        # جلب البيانات اللحظية
        data = ticker.history(period="1d", interval="1m")
        
        if data.empty:
            return None
        
        # استخراج البيانات
        last_row = data.iloc[-1]
        price = float(last_row['Close'])
        volume = int(last_row['Volume'])
        market_cap = info.get('marketCap', 0)
        prev_close = info.get('previousClose', price)
        change = ((price - prev_close) / prev_close) * 100 if prev_close else 0
        
        # التحقق من صحة البيانات
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
        logging.warning(f"⚠️ [yfinance] خطأ في {symbol}: {e}")
        return None

# ================= VOLUME RATIO =================
def calculate_rel_vol(volume):
    """حساب الحجم النسبي (تقديري)"""
    avg_volume = 50000
    return volume / avg_volume if avg_volume > 0 else 1.0

# ================= FILTER =================
def valid(stock, is_premarket=False):
    try:
        price = float(stock.get("close") or 0)
        change = float(stock.get("change") or 0)
        vol = float(stock.get("volume") or 0)
        market_cap = float(stock.get("market_cap") or 0)

        # تصفية حسب الفئة السعرية
        if price < MIN_PRICE or price > MAX_PRICE:
            return False
        
        # تصفية حسب القيمة السوقية
        if market_cap < MIN_MARKET_CAP or market_cap > MAX_MARKET_CAP:
            return False
        
        # تصفية حسب الجلسة
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
    print(f"🔍 المصدر: Yahoo Finance (yfinance) - بدون حدود للطلبات")

    await send("📊 *M60 Hunter V8 - Yahoo Finance (بدون حدود)*")

    # قائمة الأسهم التجريبية (للتجربة - سنقوم بجلبها من Finnhub لاحقاً)
    # مؤقتاً، نستخدم قائمة صغيرة للاختبار
    test_symbols = ["AAPL", "TSLA", "NVDA", "AMD", "AMZN", "MSFT", "GOOGL", "META", "NFLX", "INTC"]
    
    while True:
        current_session = get_session()
        print(f"\n🔄 دورة جديدة - {current_session}")
        
        # ===== جلب البيانات من Yahoo Finance =====
        stocks = []
        
        for symbol in test_symbols:
            try:
                data = get_stock_data(symbol)
                if data:
                    stocks.append(data)
                    print(f"✅ {symbol}: ${data['close']:.2f}, {data['change']:.2f}%, حجم: {data['volume']:,}, قيمة: ${data['market_cap']/1_000_000:.1f}M")
                await asyncio.sleep(0.5)  # انتظار نصف ثانية بين الطلبات
            except Exception as e:
                logging.error(f"⚠️ خطأ في {symbol}: {e}")
                continue
        
        print(f"📡 تم جلب {len(stocks)} سهماً")
        
        if not stocks:
            print("⚠️ لم يتم جلب أي أسهم، إعادة المحاولة...")
            await asyncio.sleep(30)
            continue
        
        # ===== تطبيق الشروط =====
        is_premarket = (current_session == "premarket" or current_session == "afterhours")
        signals = detect(stocks, is_premarket)
        
        print(f"✅ signals: {len(signals)}")
        
        for s in signals:
            await send_alert(*s)
            await asyncio.sleep(1)
        
        # ===== ننتظر 60 ثانية قبل الدورة التالية =====
        print(f"⏳ انتظار 60 ثانية...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
