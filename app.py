import os
import asyncio
import logging
import pytz
import requests
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

Thread(target=run_web_server, daemon=True).start()

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
MIN_MARKET_CAP = 10_000_000
MAX_MARKET_CAP = 150_000_000

last_alert = {}

# ================= TIME =================
def ny():
    return datetime.now(pytz.timezone("America/New_York"))

# ================= TELEGRAM =================
async def send(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

# ================= GET ALL SYMBOLS =================
def get_all_symbols():
    """جلب قائمة الرموز من Finnhub"""
    try:
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={FINNHUB_KEY}"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return data
        return []
    except Exception as e:
        logging.error(f"خطأ في جلب القائمة: {e}")
        return []

# ================= CHECK STOCK =================
def check_stock(symbol):
    """جلب بيانات السهم وتطبيق الشروط"""
    try:
        # جلب البيانات
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        price = data.get("c", 0)
        change = data.get("dp", 0)
        volume = data.get("v", 0)
        
        if price <= 0 or volume <= 0:
            return None
        
        # التحقق من الشروط
        if price < MIN_PRICE or price > MAX_PRICE:
            return None
        if volume < MIN_VOLUME:
            return None
        if change < MIN_MOVE:
            return None
            
        # جلب القيمة السوقية
        market_cap = None
        try:
            profile_url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_KEY}"
            profile_res = requests.get(profile_url, timeout=10)
            if profile_res.status_code == 200:
                profile_data = profile_res.json()
                mc = profile_data.get("marketCapitalization")
                if mc:
                    market_cap = float(mc) * 1_000_000
        except:
            pass
        
        if market_cap and (market_cap < MIN_MARKET_CAP or market_cap > MAX_MARKET_CAP):
            return None
        
        return {
            "ticker": symbol,
            "price": price,
            "change": change,
            "volume": volume,
            "market_cap": market_cap
        }
        
    except Exception as e:
        return None

# ================= MAIN =================
async def main():
    await send("🔥 *M60 Hunter - بدء العمل*")
    
    while True:
        try:
            # جلب القائمة
            all_symbols = get_all_symbols()
            if not all_symbols:
                await asyncio.sleep(30)
                continue
            
            # أخذ أول 50 سهم
            symbols_to_check = all_symbols[:50]
            logging.info(f"📡 جاري تدقيق {len(symbols_to_check)} رمزاً...")
            
            for item in symbols_to_check:
                symbol = item.get("symbol")
                if not symbol:
                    continue
                
                # تأخير 1.5 ثانية
                await asyncio.sleep(1.5)
                
                stock = check_stock(symbol)
                if stock:
                    now = ny().strftime("%H:%M:%S")
                    msg = (
                        f"📊 *{symbol} — {now}* 📊\n\n"
                        f"🔹 *السعر:* `${stock['price']:.2f}`\n"
                        f"🔹 *الارتفاع:* `+{stock['change']:.2f}%`\n"
                        f"🔹 *الحجم:* `{stock['volume']:,}`\n"
                        f"🔹 *القيمة السوقية:* `${stock['market_cap']/1_000_000:.1f}M`"
                    )
                    await send(msg)
                    await asyncio.sleep(1)
            
            # انتظار دقيقة قبل الدورة التالية
            await asyncio.sleep(60)
            
        except Exception as e:
            logging.error(f"⚠️ خطأ في الحلقة الرئيسية: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
