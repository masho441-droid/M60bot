import os
import asyncio
import aiohttp
import time
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== DUMMY WEB SERVER ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Test Hunter is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ===============================================================

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
STOCKDATA_TOKEN = os.getenv("STOCKDATA_TOKEN")

if not TOKEN or not CHAT_ID or not STOCKDATA_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN, CHAT_ID أو STOCKDATA_TOKEN غير موجودة")

bot = Bot(token=TOKEN)
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

# ====================== STRATEGY SETTINGS (مخففة جداً) ==========
MIN_PRICE = 0.1
MAX_PRICE = 100.0
MIN_VOLUME = 1000
MIN_VOLUME_SPIKE = 0.1
MIN_PRICE_CHANGE = 0.1
ALERT_COOLDOWN = 60  # دقيقة واحدة فقط للاختبار
SYMBOLS_LIMIT = 50   # عدد أقل للاختبار

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(MAKKAH_TZ).date()

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ====================== FETCH SYMBOLS ===========================
async def fetch_active_symbols(session):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]}
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "volume"]
    }
    try:
        async with session.post(url, json=payload, timeout=15) as resp:
            data = await resp.json()
            symbols = []
            for item in data.get('data', []):
                d = item['d']
                if len(d) >= 3 and None not in [d[1], d[2]]:
                    symbols.append(d[0])
            return symbols[:SYMBOLS_LIMIT]
    except Exception as e:
        print(f"❌ فشل جلب القائمة: {e}")
        return []

# ====================== FETCH QUOTES ============================
async def fetch_quotes(session, symbols):
    if not symbols:
        return []
    
    symbols_param = ",".join(symbols)
    url = f"https://api.stockdata.org/v1/data/quote?symbols={symbols_param}&api_token={STOCKDATA_TOKEN}&extended_hours=true"
    
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                print(f"❌ فشل جلب البيانات: {resp.status}")
                return []
            data = await resp.json()
            quotes = data.get('data', [])
            print(f"✅ تم جلب {len(quotes)} سهماً من StockData.org")
            
            # ======== اختبار: إرسال أول 3 أسهم إلى القناة ========
            for i, quote in enumerate(quotes[:3]):
                await send_telegram(f"🧪 اختبار {i+1}: {quote.get('symbol')} - السعر: ${quote.get('price')} - الحجم: {quote.get('volume')}")
            
            return quotes
    except Exception as e:
        print(f"❌ خطأ في StockData.org: {e}")
        return []

# ====================== DETECT EXPLOSION (مخففة جداً) ==========
async def detect_explosion(quote):
    try:
        symbol = quote.get('symbol')
        price = quote.get('price')
        volume = quote.get('volume')
        change = quote.get('change_percent', 0)

        if not symbol or not price or not volume:
            return None

        # شروط مخففة جداً (للتأكد من ظهور تنبيه)
        is_explosion = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume >= MIN_VOLUME
        )

        if is_explosion:
            target1 = price * 1.05
            target2 = price * 1.10
            target3 = price * 1.20
            stop_loss = price * 0.97

            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": 1.0,
                "price_change": change if change else 0.5,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "stop_loss": stop_loss,
                "time": datetime.now(NY_TZ).strftime("%H:%M")
            }
        return None
    except Exception as e:
        print(f"⚠️ خطأ في تحليل {quote.get('symbol')}: {e}")
        return None

def can_alert(symbol):
    now = time.time()
    if symbol in alert_history:
        if now - alert_history[symbol] < ALERT_COOLDOWN:
            return False
    alert_history[symbol] = now
    return True

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date

    await send_telegram("🔥 *M60 - Test Hunter يعمل (للاختبار)*")
    print("🚀 بدء الاختبار...")

    while True:
        try:
            now_makkah = datetime.now(MAKKAH_TZ)
            if now_makkah.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_makkah.date()

            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة")
                    await asyncio.sleep(30)
                    continue

                quotes = await fetch_quotes(session, symbols)
                if not quotes:
                    print("⚠️ لا توجد بيانات من StockData.org")
                    await asyncio.sleep(30)
                    continue

                for quote in quotes:
                    result = await detect_explosion(quote)
                    if result and can_alert(result["symbol"]):
                        alert_counters[result["symbol"]] = alert_counters.get(result["symbol"], 0) + 1
                        alert_num = alert_counters[result["symbol"]]

                        msg = (
                            f"💥 *اختبار تنبيه*\n\n"
                            f"📊 الرمز: `{result['symbol']}`\n"
                            f"💰 السعر: `${result['price']:.2f}`\n"
                            f"📈 الزخم: `+{result['price_change']:.2f}%`\n"
                            f"🎯 الأهداف: `{result['target1']:.2f}` → `{result['target2']:.2f}` → `{result['target3']:.2f}`\n"
                            f"🛑 وقف الخسارة: `{result['stop_loss']:.2f}`\n"
                            f"🕒 وقت الكشف: `{result['time']}`\n"
                            f"🔢 تنبيه #{alert_num}\n\n"
                            f"⚠️ اختبار فقط"
                        )
                        await send_telegram(msg)
                        print(f"✅ تم إرسال تنبيه لـ {result['symbol']}")
                        await asyncio.sleep(1)

                print(f"⏳ انتظار 30 ثانية...")
                await asyncio.sleep(30)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
