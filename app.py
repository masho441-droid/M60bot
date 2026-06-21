import os
import asyncio
import random
import logging
import pytz
import requests
from datetime import datetime, time as dt_time
from telegram import Bot
from tradingview_screener import Query  # <-- التعديل هنا

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
MIN_MOVE = 1.2
MIN_VOLUME = 100000
COOLDOWN = 120

last_price = {}
last_alert = {}
alert_counters = {}

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
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(e)

# ================= DATA LAYER (المعدلة) =================
def fetch_screener():
    try:
        q = Query()
        q = q.select('ticker', 'close', 'change', 'volume', 'market_cap_basic', 'relative_volume_24h')
        q = q.where(f'close >= {MIN_PRICE} AND close <= {MAX_PRICE}')
        q = q.order_by('volume', ascending=False)
        q = q.limit(200)

        _, df = q.get_scanner_data()
        return df.to_dict("records") if df is not None else []

    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return []

# ================= FINNHUB CONFIRMATION =================
def finnhub_price(symbol):
    if not FINNHUB_KEY:
        return None

    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=5)
        data = r.json()
        return float(data.get("c")) if data.get("c") else None
    except:
        return None

# ================= FILTER =================
def valid(s):
    try:
        sym = s.get("ticker") or s.get("symbol")
        price = float(s.get("close") or s.get("price") or 0)
        change = float(str(s.get("change") or 0).replace("%", ""))
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

        sym = s.get("ticker") or s.get("symbol")
        price = float(s.get("close") or s.get("price") or 0)

        prev = last_price.get(sym)
        if not prev:
            last_price[sym] = price
            continue

        move = ((price - prev) / prev) * 100 if prev else 0
        last_price[sym] = price

        if move < MIN_MOVE:
            continue

        now = ny().timestamp()
        if now - last_alert.get(sym, 0) < COOLDOWN:
            continue

        confirm = finnhub_price(sym)
        if confirm:
            diff = abs(confirm - price) / price * 100
            if diff > 2.5:
                continue

        last_alert[sym] = now
        alert_counters[sym] = alert_counters.get(sym, 0) + 1

        alerts.append((sym, price, move, alert_counters[sym]))

    return alerts

# ================= ALERT =================
async def alert(sym, price, move, alert_num):
    msg = (
        f"🔥 *M60 Hunter - صيد مبكر*\n\n"
        f"📌 *السهم:* `{sym}` | 🔢 *تنبيه:* `#{alert_num}`\n"
        f"💰 *السعر:* `${price:.2f}`\n"
        f"📈 *الحركة:* `+{move:.2f}%`\n\n"
        f"🕒 NY {ny().strftime('%H:%M:%S')} | SA {sa().strftime('%H:%M:%S')}"
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
    await send("🔥 *M60 Hunter - صيد مبكر متقدم*")
    asyncio.create_task(heartbeat())

    while True:
        if session() == "closed":
            await asyncio.sleep(300)
            continue

        stocks = fetch_screener()
        signals = detect(stocks)

        logging.info(f"signals: {len(signals)}")

        for s in signals:
            try:
                await alert(*s)
                await asyncio.sleep(random.uniform(0.3, 0.7))
            except Exception as e:
                logging.error(e)

        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
