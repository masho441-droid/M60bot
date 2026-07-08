import os
import asyncio
import aiohttp
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
STOCKDATA_TOKEN = os.getenv("STOCKDATA_TOKEN")

bot = Bot(token=TOKEN)
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.5
MAX_PRICE = 15.0
MIN_VOLUME = 100000 # خفضتها قليلاً لضمان ظهور نتائج
MIN_PRICE_CHANGE = 1.0 # خفضتها لـ 1% لتجربة التنبيهات
ALERT_COOLDOWN = 1800 

# ====================== WEB SERVER (Keep Alive) =================
app = Flask(__name__)
@app.route("/")
def home(): return "M60 Hunter is Online", 200

def run_web(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
threading.Thread(target=run_web, daemon=True).start()

# ====================== FUNCTIONS ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(f"❌ خطأ تليجرام: {e}")

async def fetch_active_symbols(session):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [{"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
                   {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]}],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "volume"]
    }
    try:
        async with session.post(url, json=payload, timeout=10) as resp:
            data = await resp.json()
            return [item['d'][0] for item in data.get('data', []) if item['d']]
    except: return []

async def fetch_quotes(session, symbols):
    # نأخذ أول 50 رمزاً فقط لتجنب تجاوز حد الـ API
    symbols_subset = ",".join(symbols[:50])
    url = f"https://api.stockdata.org/v1/data/quote?symbols={symbols_subset}&api_token={STOCKDATA_TOKEN}"
    try:
        async with session.get(url, timeout=10) as resp:
            data = await resp.json()
            return data.get('data', [])
    except: return []

async def detect_explosion(quote):
    symbol = quote.get('symbol', 'N/A')
    price = float(quote.get('price', 0))
    volume = float(quote.get('volume', 0))
    change = float(quote.get('change_percent', 0))

    # طباعة الفحص في الـ Logs
    print(f"🔍 فحص {symbol}: السعر={price}, الحجم={volume}, التغير={change}%")

    if price >= MIN_PRICE and price <= MAX_PRICE and volume >= MIN_VOLUME and change >= MIN_PRICE_CHANGE:
        return {
            "symbol": symbol, "price": price, "volume": volume,
            "change": change, "time": datetime.now(NY_TZ).strftime("%H:%M")
        }
    return None

async def main_loop():
    alert_history = {}
    print("🚀 M60 Hunter يعمل الآن...")
    await send_telegram("🤖 *M60 Hunter started successfully!*")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session)
                quotes = await fetch_quotes(session, symbols)
                
                for quote in quotes:
                    res = await detect_explosion(quote)
                    if res:
                        # فحص التكرار
                        if time.time() - alert_history.get(res['symbol'], 0) > ALERT_COOLDOWN:
                            msg = (f"💥 *انفجار في {res['symbol']}*\n"
                                   f"💰 السعر: ${res['price']:.2f}\n"
                                   f"📈 التغير: +{res['change']:.2f}%\n"
                                   f"📊 الحجم: {res['volume']:,}\n"
                                   f"🕒 الوقت: {res['time']} (NY)")
                            await send_telegram(msg)
                            alert_history[res['symbol']] = time.time()
                            print(f"✅ تم إرسال تنبيه لـ {res['symbol']}")

            await asyncio.sleep(60)
        except Exception as e:
            print(f"❌ خطأ في الحلقة الرئيسية: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())
