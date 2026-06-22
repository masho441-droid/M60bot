import os
import asyncio
import logging
import pytz
import requests
from datetime import datetime, time as dt_time
from telegram import Bot
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# ================= SESSION WITH RETRY =================
def get_session():
    """جلسة طلبات مع إعادة المحاولة التلقائية"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.timeout = 30
    return session

session = get_session()

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_MOVE = 1.0
MIN_VOLUME = 50000
COOLDOWN = 120
MIN_REL_VOL = 1.2

# إعدادات منفصلة للبري ماركت (أخف)
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

# ================= FINNHUB - جلب الأسهم الأكثر زخماً =================
def fetch_top_momentum_stocks(limit=50, is_premarket=False):
    """
    يجلب القائمة الكاملة من Finnhub، يرتبها حسب الزخم،
    ويأخذ أفضل `limit` سهماً
    """
    print(f"📡 [Finnhub] جاري جلب الأسهم الأكثر زخماً...")
    
    try:
        # ===== الخطوة 1: جلب القائمة الكاملة (طلب واحد) =====
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        response = session.get(url, timeout=30)
        
        if response.status_code != 200:
            print(f"⚠️ خطأ في الطلب: {response.status_code}")
            return []
            
        all_symbols = response.json()
        
        if not isinstance(all_symbols, list):
            print("⚠️ Finnhub أعاد بيانات غير متوقعة")
            return []
        
        print(f"📡 تم استلام {len(all_symbols)} رمزاً")
        
        # ===== تحديد عدد الرموز التي سنفحصها =====
        if is_premarket:
            # في البري: نفحص 100 رمزاً فقط (توفير للطلبات)
            symbols_to_check = all_symbols[:100]
        else:
            # في التداول العادي: نفحص بأقصى طاقة (حتى 500)
            symbols_to_check = all_symbols[:500]
        
        print(f"📡 سيتم فحص {len(symbols_to_check)} رمزاً")
        
        stocks = []
        request_count = 0
        max_requests = 55 if is_premarket else 55  # نترك 5 طلبات احتياطية
        
        # ===== الخطوة 2: جلب بيانات كل رمز =====
        for item in symbols_to_check:
            symbol = item.get("symbol")
            if not symbol:
                continue
            
            # نتحكم بعدد الطلبات
            if request_count >= max_requests:
                print(f"⚠️ وصلنا لحد {max_requests} طلب، نتوقف مؤقتاً")
                break
            
            try:
                quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
                quote_res = session.get(quote_url, timeout=10)  # زيادة المهلة إلى 10 ثوانٍ
                request_count += 1
                
                if quote_res.status_code != 200:
                    continue
                    
                quote = quote_res.json()
                
                price = quote.get("c", 0)
                change = quote.get("dp", 0)
                volume = quote.get("v", 0)
                
                # ===== تصفية أولية سريعة =====
                if price <= 0 or volume <= 0:
                    continue
                
                # حساب الزخم (نسبة التغير × الحجم)
                momentum = abs(change) * volume
                
                stocks.append({
                    "ticker": symbol,
                    "close": price,
                    "change": change,
                    "volume": volume,
                    "momentum": momentum
                })
                
            except requests.exceptions.Timeout:
                logging.warning(f"⏱️ مهلة انتهت للسهم {symbol}، تخطي")
                continue
            except Exception as e:
                logging.warning(f"⚠️ خطأ في {symbol}: {e}")
                continue
        
        print(f"📡 تم جمع {len(stocks)} سهماً")
        
        if not stocks:
            print("⚠️ لم يتم جمع أي أسهم!")
            return []
        
        # ===== الخطوة 3: ترتيب حسب الزخم (الأعلى أولاً) =====
        stocks.sort(key=lambda x: x["momentum"], reverse=True)
        
        # ===== الخطوة 4: نأخذ أفضل `limit` سهماً =====
        top_stocks = stocks[:limit]
        
        print(f"📡 [Finnhub] تم اختيار أفضل {len(top_stocks)} سهماً من حيث الزخم")
        
        # طباعة للفحص
        for i, s in enumerate(top_stocks[:5]):
            print(f"  {i+1}. {s['ticker']}: ${s['close']:.2f}, {s['change']:.2f}%, حجم: {s['volume']:,}, الزخم: {s['momentum']:,}")
        
        return top_stocks
        
    except requests.exceptions.Timeout:
        logging.error("⏱️ مهلة الاتصال بـ Finnhub انتهت!")
        return []
    except Exception as e:
        logging.error(f"Finnhub error: {e}")
        return []

# ================= YAHOO (للتداول العادي فقط) =================
def fetch_yahoo_stocks(symbols):
    """جلب بيانات Yahoo لرموز محددة"""
    print(f"📡 [Yahoo] جاري جلب البيانات لـ {len(symbols)} سهماً...")
    
    stocks = []
    
    for symbol in symbols[:10]:  # نأخذ 10 رموزاً فقط لتوفير الطلبات
        if not symbol:
            continue
            
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = session.get(url, headers=headers, timeout=10)
            
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
            logging.warning(f"⚠️ Yahoo error for {symbol}: {e}")
            continue
    
    print(f"📡 [Yahoo] تم جلب {len(stocks)} سهماً")
    return stocks

# ================= MERGE STOCKS =================
def merge_stocks(finnhub_stocks, yahoo_stocks):
    """دمج الأسهم من Finnhub و Yahoo"""
    all_stocks = finnhub_stocks + yahoo_stocks
    
    seen = set()
    unique_stocks = []
    for s in all_stocks:
        ticker = s.get("ticker")
        if ticker and ticker not in seen:
            seen.add(ticker)
            unique_stocks.append(s)
    
    # ترتيب حسب الزخم
    unique_stocks.sort(key=lambda x: (abs(x["change"]) * x["volume"]), reverse=True)
    
    print(f"📡 تم دمج {len(unique_stocks)} سهماً فريداً")
    return unique_stocks

# ================= VOLUME RATIO =================
def calculate_rel_vol(volume, symbol):
    """حساب الحجم النسبي (تقديري)"""
    avg_volume = 50000
    return volume / avg_volume if avg_volume > 0 else 1.0

# ================= FILTER =================
def valid(s, is_premarket=False):
    try:
        sym = s.get("ticker")
        price = float(s.get("close") or 0)
        change = float(s.get("change") or 0)
        vol = float(s.get("volume") or 0)

        if not sym:
            return False
        
        # الفئة السعرية
        if price < MIN_PRICE or price > MAX_PRICE:
            return False
        
        # شروط حسب الفترة
        if is_premarket:
            if vol < PREMARKET_MIN_VOLUME:
                return False
            if change < PREMARKET_MIN_MOVE:
                return False
        else:
            if vol < MIN_VOLUME:
                return False
            if change < MIN_MOVE:
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

        # شرط الحجم النسبي حسب الفترة
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
    print(f"📊 الفئة السعرية: ${MIN_PRICE} - ${MAX_PRICE}")
    print(f"🔍 بدء الحلقة الرئيسية...")

    await send("🔥 *M60 Hunter V5 - صيد الزخم*")
    asyncio.create_task(heartbeat())

    while True:
        current_session = session()
        print(f"\n🔄 دورة جديدة - الجلسة: {current_session}")
        
        if current_session == "closed":
            print("⏸️ السوق مغلق. انتظار 5 دقائق...")
            await asyncio.sleep(300)
            continue

        # ===== استراتيجية مختلفة حسب الفترة =====
        if current_session == "premarket":
            print("🌅 [بري ماركت] وضع التركيز على الزخم - 50 سهماً أفضل")
            
            # جلب أفضل 50 سهماً من حيث الزخم من Finnhub
            top_stocks = fetch_top_momentum_stocks(limit=50, is_premarket=True)
            
            if not top_stocks:
                print("⚠️ لم يتم جلب أي أسهم، إعادة المحاولة بعد 30 ثانية")
                await asyncio.sleep(30)
                continue
            
            # تطبيق الشروط على أفضل 50
            signals = detect(top_stocks, is_premarket=True)
            
        else:  # regular أو afterhours
            print("📈 [السوق المفتوح] وضع الاستراتيجية الكاملة - بأقصى طاقة")
            
            # جلب أفضل 50 سهماً من Finnhub (حسب الزخم)
            finnhub_top = fetch_top_momentum_stocks(limit=50, is_premarket=False)
            
            if not finnhub_top:
                print("⚠️ لم يتم جلب أي أسهم من Finnhub")
                await asyncio.sleep(30)
                continue
            
            # جلب رموز أفضل 10 سهماً لـ Yahoo
            yahoo_symbols = [s["ticker"] for s in finnhub_top[:10]]
            yahoo_stocks = fetch_yahoo_stocks(yahoo_symbols)
            
            # دمج البيانات
            stocks = merge_stocks(finnhub_top, yahoo_stocks)
            
            # تطبيق الشروط الكاملة
            signals = detect(stocks, is_premarket=False)

        logging.info(f"✅ signals: {len(signals)}")

        if signals:
            print(f"🎯 تم العثور على {len(signals)} إشارة!")
            for s in signals:
                print(f"  📊 {s[0]}: ${s[1]:.2f}, {s[2]:.2f}%")
                try:
                    await send_alert(*s)
                    await asyncio.sleep(1)
                except Exception as e:
                    logging.error(e)
        else:
            print("❌ لا توجد إشارات في هذه الدورة")

        # ===== ننتظر 60 ثانية =====
        print(f"⏳ انتظار 60 ثانية...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
