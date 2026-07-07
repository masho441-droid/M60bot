import os
import asyncio
import aiohttp
import time
import yfinance as yf
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== DUMMY WEB SERVER ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Smart StockData Hunter is running", 200

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

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.1
MAX_PRICE = 5.0
MIN_VOLUME = 200000
MIN_VOLUME_SPIKE = 5.0
MIN_PRICE_CHANGE = 5.0
ALERT_COOLDOWN = 1800  # 30 دقيقة
SYMBOLS_LIMIT = 200

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(MAKKAH_TZ).date()
last_premarket_sent = False
last_market_open_sent = False

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ====================== FETCH SYMBOLS (TradingView) =============
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

# ====================== FETCH HISTORICAL DATA (yfinance) ========
async def fetch_historical_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1mo")
        if hist.empty:
            return None
        avg_volume_10 = hist["Volume"].iloc[-10:].mean()
        high_20d = hist["High"].iloc[-20:].max()
        return {"avg_volume_10": avg_volume_10, "high_20d": high_20d}
    except:
        return None

# ====================== FETCH QUOTES (StockData.org) ============
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
            return quotes
    except Exception as e:
        print(f"❌ خطأ في StockData.org: {e}")
        return []

# ====================== DETECT EXPLOSION ========================
async def detect_explosion(quote):
    try:
        symbol = quote.get('symbol')
        price = quote.get('price')
        volume = quote.get('volume')
        change = quote.get('change_percent', 0)

        if not symbol or not price or not volume:
            return None

        # جلب البيانات التاريخية (يتم تخزينها مؤقتاً لتقليل الطلبات)
        hist = await fetch_historical_data(symbol)
        if not hist:
            return None

        avg_volume_10 = hist["avg_volume_10"]
        high_20d = hist["high_20d"]

        volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 1.0
        price_breakout = ((price - high_20d) / high_20d) * 100 if high_20d > 0 else 0

        is_explosion = (
            MIN_PRICE <= price <= MAX_PRICE and
            volume >= MIN_VOLUME and
            volume_spike >= MIN_VOLUME_SPIKE and
            change > MIN_PRICE_CHANGE and
            price > high_20d
        )

        if is_explosion:
            target1 = price * 1.20
            target2 = price * 1.50
            target3 = price * 2.00
            stop_loss = price * 0.95

            return {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "volume_spike": volume_spike,
                "price_change": change,
                "price_breakout": price_breakout,
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
    global last_reset_date, last_premarket_sent, last_market_open_sent

    await send_telegram("🔥 *M60 - Smart StockData Hunter يعمل*")
    print("🚀 بدء العمل مع طلب واحد لكل دورة...")

    while True:
        try:
            now_makkah = datetime.now(MAKKAH_TZ)
            now_hour = now_makkah.hour
            now_minute = now_makkah.minute

            if now_hour == 11 and now_minute == 0 and not last_premarket_sent:
                await send_telegram("🌅 *بداية البري ماركت (11 ص بتوقيت مكة)*")
                last_premarket_sent = True
                print("✅ تم إرسال رسالة البري ماركت")

            if now_hour == 16 and now_minute == 30 and not last_market_open_sent:
                await send_telegram("🔔 *افتتاح السوق الرسمي (4:30 م بتوقيت مكة)*")
                last_market_open_sent = True
                print("✅ تم إرسال رسالة افتتاح السوق")

            if now_hour == 0 and now_minute == 0:
                last_premarket_sent = False
                last_market_open_sent = False

            if now_makkah.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_makkah.date()
                print("✅ تم إعادة ضبط العدادات اليومية")

            async with aiohttp.ClientSession() as session:
                # 1. جلب قائمة الأسهم (مجاني)
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة")
                    await asyncio.sleep(30)
                    continue

                # 2. طلب واحد لجميع الأسهم من StockData.org
                quotes = await fetch_quotes(session, symbols)
                if not quotes:
                    print("⚠️ لا توجد بيانات من StockData.org")
                    await asyncio.sleep(30)
                    continue

                # 3. تحليل كل سهم محلياً (بدون طلبات إضافية)
                for quote in quotes:
                    result = await detect_explosion(quote)
                    if result and can_alert(result["symbol"]):
                        alert_counters[result["symbol"]] = alert_counters.get(result["symbol"], 0) + 1
                        alert_num = alert_counters[result["symbol"]]

                        msg = (
                            f"💥 *انفجار كبير - سيولة هائلة*\n\n"
                            f"📊 الرمز: `{result['symbol']}`\n"
                            f"💰 السعر: `${result['price']:.2f}`\n"
                            f"📈 الحجم النسبي: `{result['volume_spike']:.1f}x`\n"
                            f"📈 الزخم: `+{result['price_change']:.2f}%`\n"
                            f"🚀 اختراق القمة: `+{result['price_breakout']:.1f}%`\n"
                            f"🎯 الأهداف: `{result['target1']:.2f}` → `{result['target2']:.2f}` → `{result['target3']:.2f}`\n"
                            f"🛑 وقف الخسارة: `{result['stop_loss']:.2f}`\n"
                            f"🕒 وقت الكشف (نيويورك): `{result['time']}`\n"
                            f"🔢 تنبيه #{alert_num} لهذا السهم\n\n"
                            f"⚠️ انفجار وشيك - راقب السهم فوراً"
                        )
                        await send_telegram(msg)
                        print(f"✅ تم إرسال تنبيه لـ {result['symbol']}")
                        await asyncio.sleep(1)

                print(f"⏳ انتظار 60 ثانية... (طلبات StockData: 1 لكل دورة)")
                await asyncio.sleep(60)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
