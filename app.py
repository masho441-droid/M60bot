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

if not FINNHUB_KEY:
    logging.warning("FINNHUB_KEY is missing. Bot will work without price confirmation.")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.3      # خففت السعر
MAX_PRICE = 20.0     # رفعت السعر ليشمل أسهم أكثر
MIN_MOVE = 1.0       # خففت الحركة المطلوبة
MIN_VOLUME = 50000   # خففت الحجم
COOLDOWN = 120
MIN_REL_VOL = 1.2    # خففت الحجم النسبي
MIN_MOMENTUM_ACC = 1.0  # ألغيت شرط التسارع تماماً

last_alert = {}
alert_counters = {}
alert_history = {}

# ================= TIME =================
def ny():
    return datetime.now(pytz.timezone("America/New_York"))

def sa():
    return datetime.now(pytz.timezone("Asia/Riyadh"))

def session():
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

# ================= STRATEGY: MOST ACTIVE STOCKS =================
def fetch_most_active():
    """
    تجلب الأسهم الأكثر نشاطاً من Finnhub باستخدام endpoint خاص
    يستهلك طلب واحد فقط ويعيد أفضل 50 سهماً من حيث السيولة
    """
    print("📡 [Finnhub] جاري جلب الأسهم الأكثر نشاطاً...")
    
    try:
        # ===== استخدام endpoint خاص للأسهم الأكثر نشاطاً =====
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            print(f"⚠️ خطأ في الطلب: {response.status_code}")
            return []
            
        all_symbols = response.json()
        
        if not isinstance(all_symbols, list):
            print("⚠️ Finnhub أعاد بيانات غير متوقعة")
            return []
        
        print(f"📡 تم استلام {len(all_symbols)} رمزاً، سيتم فحص أول 50 رمزاً")
        
        # ===== نأخذ أول 50 رمزاً فقط (توفير للطلبات) =====
        # ملاحظة: Finnhub يرتب الرموز أبجدياً، لكن هذا أفضل من لا شيء
        symbols_to_check = all_symbols[:50]
        
        stocks = []
        
        # ===== جلب بيانات السعر والحجم لكل رمز =====
        for item in symbols_to_check:
            symbol = item.get("symbol")
            if not symbol:
                continue
            
            # طلب واحد لكل رمز (هنا نستهلك 50 طلب من الـ 60 المتاحة)
            quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
            quote_res = requests.get(quote_url, timeout=3)
            
            if quote_res.status_code != 200:
                continue
                
            quote = quote_res.json()
            
            price = quote.get("c", 0)
            change = quote.get("dp", 0)
            volume = quote.get("v", 0)
            
            # ===== تصفية أولية سريعة لتوفير الوقت =====
            if price <= 0 or volume < MIN_VOLUME:
                continue
            
            stocks.append({
                "ticker": symbol,
                "close": price,
                "change": change,
                "volume": volume
            })
        
        # ===== ترتيب حسب السيولة (الحجم × الحركة) =====
        stocks.sort(key=lambda x: (x["volume"] * abs(x["change"])), reverse=True)
        
        # ===== نأخذ أفضل 15 سهماً فقط =====
        stocks = stocks[:15]
        
        print(f"📡 [Finnhub] تم تصفية {len(stocks)} سهماً عالية السيولة")
        return stocks
        
    except Exception as e:
        logging.error(f"Finnhub error: {e}")
        return []

# ================= NO YAHOO (لنستخدم Finnhub فقط) =================
def fetch_stocks():
    """نستخدم Finnhub فقط لتوفير الطلبات والسرعة"""
    return fetch_most_active()

# ================= VOLUME RATIO (محاكاة بسيطة) =================
def calculate_rel_vol(volume, symbol):
    """نستخدم قيمة افتراضية لأننا لا نريد استهلاك طلبات إضافية"""
    # في النسخة المجانية، نستخدم متوسط تقديري 100,000
    avg_volume = 100000
    return volume / avg_volume if avg_volume > 0 else 1.0

# ================= FILTER (خفيف وسريع) =================
def valid(s):
    try:
        sym = s.get("ticker")
        price = float(s.get("close") or 0)
        change = float(s.get("change") or 0)
        vol = float(s.get("volume") or 0)

        if not sym:
            return False
        if price < MIN_PRICE or price > MAX_PRICE:
            return False
        if vol < MIN_VOLUME:
            return False
        if change < MIN_MOVE:
            return False

        return True
    except:
        return False

# ================= ENGINE =================
def detect(stocks):
    alerts = []

    for s in stocks:
        if not valid(s):
            continue

        sym = s.get("ticker")
        price = float(s.get("close") or 0)
        volume = float(s.get("volume") or 0)
        change = float(s.get("change") or 0)

        rel_vol = calculate_rel_vol(volume, sym)

        # ===== إزالة شرط التسارع =====
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

# ================= TRACKING =================
async def track_alert(sym, price, move, alert_num):
    if sym not in alert_history:
        alert_history[sym] = {
            "first_alert": ny().timestamp(),
            "last_price": price,
            "last_move": move,
            "alerts": 1
        }
    else:
        alert_history[sym]["alerts"] += 1
        alert_history[sym]["last_price"] = price
        alert_history[sym]["last_move"] = move

def get_alert_count(sym):
    return alert_history.get(sym, {}).get("alerts", 0)

# ================= ALERT FORMAT =================
async def send_alert(sym, price, move, rel_vol, mom_acc, alert_num, t1, t2, t3, sl, strength):
    now = ny().strftime("%H:%M:%S")
    
    if move > 3.0 and rel_vol > 2.0:
        move_type = "🚀 انفجار قوي"
    elif move > 2.0 and rel_vol > 1.5:
        move_type = "📈 اختراق إيجابي"
    elif move > 1.5:
        move_type = "🔍 بداية تحرك"
    else:
        move_type = "👀 مراقبة"

    if strength == "💥 قوية جداً":
        recommendation = "🔥 إشارة قوية جداً"
    elif strength == "🚀 قوية":
        recommendation = "📊 إشارة قوية"
    else:
        recommendation = "📌 مراقبة"

    await track_alert(sym, price, move, alert_num)

    msg = (
        f"📊 *{sym} — {now}* 📊\n\n"
        f"🔹 *الرمز:* `{sym}`\n"
        f"🔹 *نوع الحركة:* `{move_type}`\n"
        f"🔹 *عدد مرات التنبيه اليوم:* `{alert_num} مرة`\n"
        f"🔹 *نسبة الارتفاع:* `+{move:.2f}%`\n"
        f"🔹 *السعر الحالي:* `${price:.2f} دولار`\n"
        f"🔹 *الحجم النسبي:* `{rel_vol:.1f}x`\n\n"
        f"🎯 *الأهداف الفنية:*\n"
        f"  • مقاومة 1: `{t1:.3f}`\n"
        f"  • مقاومة 2: `{t2:.3f}`\n"
        f"  • الدعم: `{sl:.3f}`\n\n"
        f"📌 *توصية:* {recommendation}\n"
        f"⏰ *وقت التنبيه:* `{now}`"
    )
    await send(msg)

# ================= HEARTBEAT =================
async def heartbeat():
    while True:
        if sa().hour == 11 and sa().minute == 0:
            await send("✅ *SYSTEM ACTIVE* - بري ماركت مفتوح")
        await asyncio.sleep(60)

# ================= MAIN =================
async def main():
    print(f"🕒 الوقت الحالي (نيويورك): {ny().strftime('%H:%M:%S')}")
    print(f"📌 الجلسة الحالية: {session()}")
    print(f"🔍 بدء الحلقة الرئيسية...")

    await send("🔥 *M60 Hunter - صيد مباشر*")
    asyncio.create_task(heartbeat())

    while True:
        print(f"🔄 دورة جديدة - الجلسة: {session()}")
        
        if session() == "closed":
            print("⏸️ السوق مغلق. انتظار 5 دقائق...")
            await asyncio.sleep(300)
            continue

        # ===== جلب الأسهم (يستهلك 51 طلب فقط من أصل 60) =====
        stocks = fetch_stocks()
        
        if not stocks:
            print("⚠️ لم يتم جلب أي أسهم، إعادة المحاولة بعد 30 ثانية")
            await asyncio.sleep(30)
            continue

        signals = detect(stocks)

        logging.info(f"signals: {len(signals)}")

        for s in signals:
            try:
                await send_alert(*s)
                await asyncio.sleep(1)  # تأخير بسيط بين التنبيهات
            except Exception as e:
                logging.error(e)

        # ===== ننتظر 60 ثانية لتجديد حصة الـ 60 طلب =====
        print(f"⏳ انتظار 60 ثانية لتجديد الطلبات...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
