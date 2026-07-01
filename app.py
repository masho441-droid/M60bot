import os
import asyncio
import aiohttp
import time
import json
import yfinance as yf
from datetime import datetime, timedelta
from telegram import Bot
from flask import Flask
import threading

# ====================== DUMMY WEB SERVER (لـ Render/Koyeb) ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "🐉 M60 Golden Cross Surge - Always On", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# =================================================================================

# ========================== الإعدادات السرية ====================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("❌ TELEGRAM_TOKEN أو CHAT_ID غير موجودة")

bot = Bot(token=TOKEN)

# ========================== إعدادات الاستراتيجية ================================
MIN_PRICE = 2.0
MAX_PRICE = 10.0
MIN_MARKET_CAP = 100_000_000
MAX_MARKET_CAP = 2_000_000_000
MIN_AVG_VOLUME_10D = 500_000
MIN_VOLUME_SPIKE = 1.5
MIN_RSI = 35
MAX_RSI = 65
ALERT_COOLDOWN = 3600  # ثانية (ساعة واحدة)

# ========================== الذاكرة المؤقتة ====================================
alert_history = {}
daily_counter = 0
last_reset_date = datetime.now().date()

# ========================== دالة الإرسال ========================================
async def send_telegram(msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ========================== جلب بيانات السهم (المصدر الرئيسي) ====================
async def fetch_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        hist = stock.history(period="3mo")
        if hist.empty or len(hist) < 50:
            return None

        price = info.get("regularMarketPrice")
        if not price:
            return None

        close = hist["Close"]
        volume = hist["Volume"]
        if len(close) < 50 or len(volume) < 10:
            return None

        sma7 = close.iloc[-7:].mean()
        sma20 = close.iloc[-20:].mean()
        sma50 = close.iloc[-50:].mean()
        avg_volume_10d = volume.iloc[-10:].mean()
        current_volume = volume.iloc[-1]
        volume_spike = current_volume / avg_volume_10d if avg_volume_10d > 0 else 0

        rsi = 50  # يمكن إضافة حساب RSI حقيقي لاحقاً
        market_cap = info.get("marketCap", 0)

        return {
            "symbol": symbol,
            "price": price,
            "volume_spike": volume_spike,
            "avg_volume_10d": avg_volume_10d,
            "sma7": sma7,
            "sma20": sma20,
            "sma50": sma50,
            "rsi": rsi,
            "market_cap": market_cap
        }
    except Exception as e:
        print(f"⚠️ فشل جلب {symbol}: {e}")
        return None

# ========================== فحص الاستراتيجية ====================================
def check_golden_cross(data):
    if not data:
        return False
    if not (MIN_PRICE <= data["price"] <= MAX_PRICE):
        return False
    if not (MIN_MARKET_CAP <= data["market_cap"] <= MAX_MARKET_CAP):
        return False
    if not (data["sma7"] > data["sma20"] > data["sma50"]):
        return False
    if data["volume_spike"] < MIN_VOLUME_SPIKE:
        return False
    if data["avg_volume_10d"] < MIN_AVG_VOLUME_10D:
        return False
    if not (MIN_RSI <= data["rsi"] <= MAX_RSI):
        return False
    return True

def can_alert(symbol):
    now = time.time()
    if symbol in alert_history:
        if now - alert_history[symbol] < ALERT_COOLDOWN:
            return False
    alert_history[symbol] = now
    return True

# ========================== جلب قائمة الأسهم النشطة ============================
async def fetch_active_symbols(session):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "market_cap_basic", "operation": "in_range", "right": [MIN_MARKET_CAP, MAX_MARKET_CAP]}
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
                if len(d) >= 4 and None not in [d[1], d[2], d[3]]:
                    symbols.append(d[0])
            return symbols[:250]
    except Exception as e:
        print(f"❌ فشل جلب القائمة: {e}")
        return []

# ========================== الحلقة الرئيسية ====================================
async def main_loop():
    global daily_counter, last_reset_date

    await send_telegram("🔥 *M60 Golden Cross Surge - تم التشغيل بنجاح*")
    print("🚀 بدء العمل...")

    while True:
        try:
            # إعادة ضبط العداد يومياً
            now = datetime.now()
            if now.date() != last_reset_date:
                daily_counter = 0
                last_reset_date = now.date()

            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة، إعادة المحاولة بعد دقيقة")
                    await asyncio.sleep(60)
                    continue

                print(f"🔍 جاري فحص {len(symbols)} سهماً...")
                tasks = [fetch_stock_data(symbol) for symbol in symbols]
                results = await asyncio.gather(*tasks)

                for data in results:
                    if data and check_golden_cross(data) and can_alert(data["symbol"]):
                        daily_counter += 1
                        msg = (
                            f"🐉 *Golden Cross Surge*\n\n"
                            f"📊 الرمز: `{data['symbol']}`\n"
                            f"💰 السعر: `${data['price']:.2f}`\n"
                            f"📈 7 SMA: `${data['sma7']:.2f}`\n"
                            f"📈 20 SMA: `${data['sma20']:.2f}`\n"
                            f"📈 50 SMA: `${data['sma50']:.2f}`\n"
                            f"📊 الحجم النسبي: `{data['volume_spike']:.1f}x`\n"
                            f"📊 متوسط 10 أيام: `{data['avg_volume_10d']:,.0f}`\n"
                            f"📉 RSI: `{data['rsi']:.0f}`\n"
                            f"🏢 القيمة السوقية: `${data['market_cap']/1e9:.2f}B`\n"
                            f"🔢 التنبيه اليومي: `#{daily_counter}`\n"
                            f"🕒 {datetime.now().strftime('%H:%M:%S')}\n\n"
                            f"✅ فرصة Golden Cross مع سيولة قوية"
                        )
                        await send_telegram(msg)
                        await asyncio.sleep(1)  # منع التكرار اللحظي

                print(f"⏳ انتهت الدورة، انتظار 90 ثانية...")
                await asyncio.sleep(90)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

# ========================== تشغيل البوت ========================================
if __name__ == "__main__":
    asyncio.run(main_loop())
