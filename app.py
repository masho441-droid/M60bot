import os
import asyncio
import time
import json
import aiohttp
from telegram import Bot
from flask import Flask
import threading
from datetime import datetime
import pytz

# ================= DUMMY WEB SERVER =================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "M60 Golden Cross Surge is running.", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ====================================================

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing TELEGRAM_TOKEN or CHAT_ID")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 2.0
MAX_PRICE = 10.0
MIN_MARKET_CAP = 100_000_000
MAX_MARKET_CAP = 2_000_000_000
MIN_VOLUME_10D = 500_000
VOLUME_SPIKE_MIN = 1.5
MIN_RSI = 35
MAX_RSI = 65

# ================= CACHE =================
ALERT_HISTORY = {}
DAILY_ALERTS = {}

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[Telegram Error] {e}")

# ================= FETCH ALL SYMBOLS (DYNAMIC) =================
async def fetch_all_symbols(session):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "nempty"},
            {"left": "market_cap_basic", "operation": "in_range", "right": [MIN_MARKET_CAP, MAX_MARKET_CAP]},
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]}
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "volume", "market_cap_basic"]
    }
    try:
        async with session.post(url, json=payload, timeout=15) as resp:
            data = await resp.json()
            symbols = []
            for item in data.get('data', []):
                d = item['d']
                if len(d) >= 4 and d[1] is not None and d[2] is not None and d[3] is not None:
                    symbols.append(d[0])
            return symbols[:200]
    except Exception as e:
        print(f"خطأ في جلب الأسهم: {e}")
        return []

# ================= FETCH STOCK DATA =================
async def fetch_stock_data(session, symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            result = data.get('chart', {}).get('result', [])
            if not result:
                return None
            meta = result[0].get('meta', {})
            indicators = result[0].get('indicators', {}).get('quote', [{}])[0]
            price = meta.get('regularMarketPrice')
            volume = meta.get('regularMarketVolume')
            market_cap = meta.get('marketCap')
            if not price or not volume or not market_cap:
                return None
            closes = indicators.get('close', [])
            volumes = indicators.get('volume', [])
            if len(closes) < 50 or len(volumes) < 10:
                return None
            sma7 = sum(closes[-7:]) / 7
            sma20 = sum(closes[-20:]) / 20
            sma50 = sum(closes[-50:]) / 50
            avg_volume_10d = sum(volumes[-10:]) / 10
            volume_spike = volume / avg_volume_10d if avg_volume_10d > 0 else 0
            rsi = 50
            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "market_cap": market_cap,
                "sma7": sma7,
                "sma20": sma20,
                "sma50": sma50,
                "avg_volume_10d": avg_volume_10d,
                "volume_spike": volume_spike,
                "rsi": rsi
            }
    except Exception as e:
        return None

# ================= CHECK STRATEGY =================
def check_golden_cross_surge(data):
    if not data:
        return False
    if not (MIN_PRICE <= data["price"] <= MAX_PRICE):
        return False
    if not (MIN_MARKET_CAP <= data["market_cap"] <= MAX_MARKET_CAP):
        return False
    if not (data["sma7"] > data["sma20"] > data["sma50"]):
        return False
    if not (data["volume_spike"] >= VOLUME_SPIKE_MIN):
        return False
    if not (data["avg_volume_10d"] >= MIN_VOLUME_10D):
        return False
    if not (MIN_RSI <= data["rsi"] <= MAX_RSI):
        return False
    return True

# ================= CAN ALERT =================
def can_alert(symbol):
    now = time.time()
    if symbol in ALERT_HISTORY:
        if now - ALERT_HISTORY[symbol] < 3600:
            return False
    ALERT_HISTORY[symbol] = now
    return True

# ================= SCAN MARKET =================
async def scan_market():
    async with aiohttp.ClientSession() as session:
        symbols = await fetch_all_symbols(session)
        if not symbols:
            print("⚠️ لا توجد أسهم، إعادة المحاولة...")
            return
        print(f"✅ جاري فحص {len(symbols)} سهماً...")
        for symbol in symbols:
            data = await fetch_stock_data(session, symbol)
            if data and check_golden_cross_surge(data) and can_alert(symbol):
                today = datetime.now().strftime("%Y-%m-%d")
                DAILY_ALERTS[today] = DAILY_ALERTS.get(today, 0) + 1
                msg = (
                    f"🐉 *Golden Cross Surge*\n\n"
                    f"📊 الرمز: `{symbol}`\n"
                    f"💰 السعر: `${data['price']:.2f}`\n"
                    f"📈 7 SMA: `${data['sma7']:.2f}`\n"
                    f"📈 20 SMA: `${data['sma20']:.2f}`\n"
                    f"📈 50 SMA: `${data['sma50']:.2f}`\n"
                    f"📊 الحجم النسبي: `{data['volume_spike']:.1f}x`\n"
                    f"📊 متوسط 10 أيام: `{data['avg_volume_10d']:,.0f}`\n"
                    f"📉 RSI: `{data['rsi']:.0f}`\n"
                    f"🏢 القيمة السوقية: `${data['market_cap']/1e9:.2f}B`\n"
                    f"🔢 التنبيه: `#{DAILY_ALERTS[today]}`\n"
                    f"🕒 {datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"✅ فرصة Golden Cross مع سيولة قوية"
                )
                await send(msg)
                print(f"📤 تم إرسال تنبيه لـ {symbol}")
            await asyncio.sleep(0.1)

# ================= MAIN LOOP =================
async def main():
    await send("🔥 *تم تشغيل Golden Cross Surge*")
    print("🚀 بدء تشغيل Golden Cross Surge...")
    while True:
        await scan_market()
        await asyncio.sleep(120)

if __name__ == "__main__":
    asyncio.run(main())
