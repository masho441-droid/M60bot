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
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

# ================= DATA LAYER (Finnhub REST API) =================
def fetch_finnhub_stocks():
    try:
        # 1. جلب قائمة الرموز النشطة
        list_url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        list_res = requests.get(list_url, timeout=10)
        symbols = list_res.json()

        stocks = []
        for item in symbols[:150]:  # حد أقصى 150 سهم لكل دورة
            symbol = item.get("symbol")
            if not symbol:
                continue

            # 2. جلب سعر السهم الفوري
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
        logging.error(f"Error fetching from Finnhub: {e}")
        return []

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

        last_alert[sym] = now
        alert_counters[sym] = alert_counters.get(sym, 0) + 1

        alerts.append((sym, price, move, alert_counters[sym]))

    return alerts

# ================= ALERT =================
async def alert(sym, price, move, alert_num):
    msg = (
        f"🔥 *M60 Hunter - صيد مباشر (Finnhub)*\n\n"
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
    await send("🔥 *M60 Hunter - صيد مباشر (Finnhub)*")
    asyncio.create_task(heartbeat())

    while True:
        if session() == "closed":
            await asyncio.sleep(300)
            continue

        stocks = fetch_finnhub_stocks()
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
