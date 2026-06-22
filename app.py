import os
import asyncio
import random
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
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_MOVE = 1.2
MIN_VOLUME = 100000
COOLDOWN = 120
MIN_REL_VOL = 1.5
MIN_MOMENTUM_ACC = 1.2

last_price = {}
last_alert = {}
alert_counters = {}
last_momentum = {}
alert_history = {}

# ================= TIME =================
def ny():
    return datetime.now(pytz.timezone("America/New_York"))

def sa():
    return datetime.now(pytz.timezone("Asia/Riyadh"))

# ================= SESSION =================
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

# ================= DATA LAYER (Finnhub + Yahoo) =================
def fetch_finnhub_stocks():
    try:
        list_url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        list_res = requests.get(list_url, timeout=10)
        symbols = list_res.json()

        stocks = []
        for item in symbols:  # إزالة [:150]
            symbol = item.get("symbol")
            if not symbol:
                continue

            quote_url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
            quote_res = requests.get(quote_url, timeout=5)
            quote = quote_res.json()

            price = quote.get("c", 0)
            change = quote.get("dp", 0)
            volume = quote.get("v", 0)

            if price <= 0 or volume <= 0:
                continue

            stocks.append({
                "ticker": symbol,
                "close": price,
                "change": change,
                "volume": volume
            })

        return stocks

    except Exception as e:
        logging.error(f"Finnhub error: {e}")
        return []

def fetch_yahoo_stocks():
    try:
        list_url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        list_res = requests.get(list_url, timeout=10)
        symbols = list_res.json()
        
        yahoo_symbols = [item.get("symbol") for item in symbols[:20] if item.get("symbol")]
        
        stocks = []
        for symbol in yahoo_symbols:
            if not symbol:
                continue
                
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=5)
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
        
        return stocks
    except Exception as e:
        logging.error(f"Yahoo error: {e}")
        return []

def merge_and_sort_stocks(finnhub_stocks, yahoo_stocks):
    all_stocks = finnhub_stocks + yahoo_stocks
    
    seen = set()
    unique_stocks = []
    for s in all_stocks:
        ticker = s.get("ticker")
        if ticker and ticker not in seen:
            seen.add(ticker)
            unique_stocks.append(s)
    
    unique_stocks.sort(
        key=lambda x: (x.get("volume", 0) * abs(x.get("change", 0))),
        reverse=True
    )
    
    return unique_stocks

# ================= VOLUME RATIO =================
def get_avg_volume(symbol):
    try:
        url = f"https://finnhub.io/api/v1/stock/earnings?symbol={symbol}&token={FINNHUB_KEY}"
        return 100000
    except:
        return 100000

def calculate_rel_vol(volume, symbol):
    avg_vol = get_avg_volume(symbol)
    return volume / avg_vol if avg_vol > 0 else 1.0

# ================= FILTER =================
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

        rel_vol = calculate_rel_vol(volume, sym)

        prev_move = last_momentum.get(sym, 0)
        current_move = float(s.get("change") or 0)

        momentum_acc = current_move / prev_move if prev_move != 0 else 1.0

        if rel_vol < MIN_REL_VOL:
            continue
        if momentum_acc < MIN_MOMENTUM_ACC:
            continue

        now = ny().timestamp()
        if now - last_alert.get(sym, 0) < COOLDOWN:
            continue

        last_momentum[sym] = current_move
        last_alert[sym] = now
        alert_counters[sym] = alert_counters.get(sym, 0) + 1

        target1 = price * 1.05
        target2 = price * 1.10
        target3 = price * 1.15
        stop_loss = price * 0.95

        if current_move > 3.0 and volume > 500000:
            strength = "💥 قوية جداً"
        elif current_move > 2.0 and volume > 200000:
            strength = "🚀 قوية"
        else:
            strength = "📈 متوسطة"

        alerts.append((sym, price, current_move, rel_vol, momentum_acc, alert_counters[sym], target1, target2, target3, stop_loss, strength))

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
        f"🔹 *الحجم النسبي:* `{rel_vol:.1f}x`\n"
        f"🔹 *التسارع:* `{mom_acc:.1f}x`\n\n"
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
    await send("🔥 *M60 Hunter - صيد مباشر (Finnhub)*")
    asyncio.create_task(heartbeat())

    while True:
        if session() == "closed":
            await asyncio.sleep(300)
            continue

        finnhub_stocks = fetch_finnhub_stocks()
        yahoo_stocks = fetch_yahoo_stocks()
        stocks = merge_and_sort_stocks(finnhub_stocks, yahoo_stocks)

        signals = detect(stocks)

        logging.info(f"signals: {len(signals)}")

        for s in signals:
            try:
                await send_alert(*s)
                await asyncio.sleep(random.uniform(0.3, 0.7))
            except Exception as e:
                logging.error(e)

        await asyncio.sleep(12)

if __name__ == "__main__":
    asyncio.run(main())
