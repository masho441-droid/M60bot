import os
import asyncio
import time
import requests
from telegram import Bot

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

if not TOKEN or not CHAT_ID or not FINNHUB_KEY:
    raise ValueError("Missing environment variables")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MAX_PRICE = 20
MIN_PRICE = 0.5
MIN_CHANGE = 1

SCAN_LIMIT = 100
SLEEP_BETWEEN = 0.8
CYCLE_SLEEP = 60

COOLDOWN = 900  # 15 min per stock
SYMBOL_CACHE_TTL = 21600  # 6 hours

# ================= STATE =================
last_alert = {}
symbol_cache = []
last_fetch_time = 0

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        print("Telegram error:", e)

# ================= SYMBOLS =================
def get_symbols():
    global symbol_cache, last_fetch_time

    now = time.time()

    if symbol_cache and (now - last_fetch_time < SYMBOL_CACHE_TTL):
        return symbol_cache

    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=30)

        if r.status_code == 200:
            symbol_cache = r.json()
            last_fetch_time = now
            print(f"Loaded symbols: {len(symbol_cache)}")

    except Exception as e:
        print("Symbol error:", e)

    return symbol_cache

# ================= QUOTE =================
def get_quote(symbol):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            return None

        d = r.json()

        return {
            "price": d.get("c", 0),
            "change": d.get("dp", 0)
        }

    except:
        return None

# ================= STRATEGY =================
def check_signal(data):
    if not data:
        return False

    price = data["price"]
    change = data["change"]

    if price <= 0:
        return False

    if not (MIN_PRICE <= price <= MAX_PRICE):
        return False

    if change < MIN_CHANGE:
        return False

    return True

# ================= COOLDOWN =================
def can_alert(symbol):
    now = time.time()

    if symbol in last_alert:
        if now - last_alert[symbol] < COOLDOWN:
            return False

    last_alert[symbol] = now
    return True

# ================= MAIN =================
async def main():

    await send("🔥 M60 PRO BOT STARTED")

    while True:
        try:
            symbols = get_symbols()

            if not symbols:
                await asyncio.sleep(30)
                continue

            selected = symbols[:SCAN_LIMIT]

            print(f"Scanning {len(selected)} symbols")

            for item in selected:

                symbol = item.get("symbol")
                if not symbol:
                    continue

                if not can_alert(symbol):
                    continue

                data = get_quote(symbol)

                if check_signal(data):

                    msg = (
                        f"🚨 *SIGNAL ALERT*\n\n"
                        f"📊 Ticker: `{symbol}`\n"
                        f"💰 Price: `{data['price']}`\n"
                        f"📈 Change: `{data['change']}%`\n"
                    )

                    await send(msg)

                await asyncio.sleep(SLEEP_BETWEEN)

            await asyncio.sleep(CYCLE_SLEEP)

        except Exception as e:
            print("Main loop error:", e)
            await asyncio.sleep(30)

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
