import os
import asyncio
import aiohttp
import time
import yfinance as yf
import pandas as pd
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== DUMMY WEB SERVER (RENDER) ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - One Request Hunter is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()
# ===============================================================

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

if not TOKEN or not CHAT_ID:
    print("⚠️ تحذير: TELEGRAM_TOKEN أو CHAT_ID غير موجودة في المتغيرات البيئية")

bot = Bot(token=TOKEN) if TOKEN else None
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_VOLUME_SPIKE = 2.0
MIN_VOLUME_ACCELERATION = 1.5
MIN_VOLUME = 300000
MIN_CHANGE = 0.6
ALERT_COOLDOWN = 900  # 15 دقيقة لمنع التكرار المزعج
SYMBOLS_LIMIT = 300

# ====================== CACHE ===================================
alert_history = {}
alert_counters = {}
last_reset_date = datetime.now(MAKKAH_TZ).date()
last_premarket_sent = False
last_market_open_sent = False

def can_alert(symbol):
    current_time = time.time()
    if symbol in alert_history:
        if current_time - alert_history[symbol] < ALERT_COOLDOWN:
            return False
    alert_history[symbol] = current_time
    return True

# ====================== TELEGRAM ================================
async def send_telegram(msg):
    if not bot:
        print("لم يتم إعداد التلغرام. الرسالة:", msg)
        return
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

# ====================== LIVE VERIFICATION (SNIPER) ==============
async def verify_live_price(session, symbol):
    # 1. القناص عبر Finnhub (الخيار الأسرع)
    if FINNHUB_API_KEY:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
        try:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
                if "c" in data and data["c"] > 0:
                    return data["c"]
        except Exception as e:
            print(f"⚠️ Finnhub API Error: {e}")

    # 2. القناص عبر Polygon (البديل الموثوق)
    if POLYGON_API_KEY:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
        try:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
                if "results" in data and len(data["results"]) > 0:
                    return data["results"][0].get("c")
        except Exception as e:
            print(f"⚠️ Polygon API Error: {e}")
            
    return None

# ====================== FETCH ALL DATA IN ONE REQUEST ===========
async def fetch_all_data(symbols):
    if not symbols:
        return {}
    
    try:
        # جلب البيانات لجميع الأسهم دفعة واحدة (الرادار) شاملة خارج أوقات التداول
        data = yf.download(
            tickers=symbols,
            period="2d",
            interval="5m",
            group_by='ticker',
            auto_adjust=True,
            threads=True,
            prepost=True
        )
        
        results = {}
        for symbol in symbols:
            try:
                # معالجة استجابة المكتبة في حال سهم واحد أو عدة أسهم
                if len(symbols) == 1:
                    df = data
                elif symbol in data:
                    df = data[symbol]
                else:
                    df = yf.Ticker(symbol).history(period="2d", interval="5m", prepost=True)
                
                if df is None or df.empty or len(df) < 5:
                    continue
                
                current = df.iloc[-1]
                price = current["Close"]
                volume = current["Volume"]
                
                avg_volume_10 = df["Volume"].iloc[-10:].mean()
                volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 1.0
                
                volume_last_5 = df["Volume"].iloc[-5:].mean()
                volume_acceleration = volume / volume_last_5 if volume_last_5 > 0 else 1.0
                
                price_change = ((price - df["Close"].iloc[-2]) / df["Close"].iloc[-2]) * 100 if len(df) > 1 else 0
                
                sma20 = df["Close"].iloc[-20:].mean() if len(df) >= 20 else price
                
                results[symbol] = {
                    "price": price,
                    "volume": volume,
                    "volume_spike": volume_spike,
                    "volume_acceleration": volume_acceleration,
                    "price_change": price_change,
                    "sma20": sma20
                }
            except Exception as e:
                continue
        
        print(f"✅ تم جلب بيانات {len(results)} سهماً (بما في ذلك خارج التداول)")
        return results
    except Exception as e:
        print(f"❌ فشل جلب البيانات: {e}")
        return {}

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date, last_premarket_sent, last_market_open_sent

    await send_telegram("🔥 *M60 - One Request Hunter يعمل*")
    print("🚀 بدء العمل مع طلب واحد لجميع الأسهم وميزة القناص...")

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
                symbols = await fetch_active_symbols(session)
                if not symbols:
                    print("⚠️ لا توجد أسهم نشطة")
                    await asyncio.sleep(30)
                    continue

                all_data = await fetch_all_data(symbols)
                if not all_data:
                    print("⚠️ لا توجد بيانات")
                    await asyncio.sleep(30)
                    continue

                print(f"🔍 جاري تحليل {len(all_data)} سهماً...")

                for symbol, data in all_data.items():
                    # التحقق المبدئي (من رادار ياهو)
                    is_potential_explosion = (
                        MIN_PRICE <= data["price"] <= MAX_PRICE and
                        data["volume"] >= MIN_VOLUME and
                        data["volume_spike"] >= MIN_VOLUME_SPIKE and
                        data["volume_acceleration"] >= MIN_VOLUME_ACCELERATION and
                        data["price_change"] > MIN_CHANGE and
                        data["price"] > data["sma20"]
                    )

                    if is_potential_explosion:
                        # التحقق الدقيق اللحظي (القناص)
                        live_price = await verify_live_price(session, symbol)
                        final_price = live_price if live_price else data["price"]
                        
                        # تأكيد الانفجار وتجاوز حد التكرار
                        if final_price > data["sma20"] and can_alert(symbol):
                            alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                            alert_num = alert_counters[symbol]

                            target1 = final_price * 1.05
                            target2 = final_price * 1.10
                            target3 = final_price * 1.20
                            stop_loss = final_price * 0.97

                            # تحديد حالة السوق
                            now_ny = datetime.now(NY_TZ)
                            market_status = "السوق الرسمي 🟢"
                            if now_ny.hour < 9 or (now_ny.hour == 9 and now_ny.minute < 30):
                                market_status = "بري ماركت 🌅"
                            elif now_ny.hour >= 16:
                                market_status = "أفتر ماركت 🌙"

                            msg = (
                                f"💥 *انفجار مبكر - سيولة قوية*\n"
                                f"وضع السوق: {market_status}\n\n"
                                f"📊 الرمز: `{symbol}`\n"
                                f"💰 السعر المباشر: `${final_price:.2f}`\n"
                                f"📈 الحجم النسبي: `{data['volume_spike']:.1f}x`\n"
                                f"⚡ تسارع الحجم: `{data['volume_acceleration']:.1f}x`\n"
                                f"📈 الزخم: `+{data['price_change']:.2f}%`\n"
                                f"📊 SMA20: `${data['sma20']:.2f}`\n"
                                f"🎯 الأهداف: `{target1:.2f}` → `{target2:.2f}` → `{target3:.2f}`\n"
                                f"🛑 وقف الخسارة: `{stop_loss:.2f}`\n"
                                f"🕒 وقت نيويورك: `{now_ny.strftime('%H:%M')}`\n"
                                f"🔢 تنبيه #{alert_num} لهذا السهم\n\n"
                                f"⚠️ المصدر: API Live Verification"
                            )
                            await send_telegram(msg)
                            print(f"✅ تم تأكيد وإرسال تنبيه لـ {symbol} بسعر {final_price}")
                            await asyncio.sleep(1)

                print(f"⏳ انتظار 60 ثانية... (طلب واحد لكل دورة)")
                await asyncio.sleep(60)

        except Exception as e:
            print(f"❌ خطأ رئيسي: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
