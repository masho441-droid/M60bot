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
import logging

logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# ====================== DUMMY WEB SERVER (RENDER) ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "🐉 M60 - Ultimate Momentum Sniper is running safely", 200

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
STOCKDATA_API_KEY = os.getenv("STOCKDATA_API_KEY")

bot = Bot(token=TOKEN) if TOKEN else None
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_VOLUME_SPIKE = 3.0          # حجم الشمعة 3 أضعاف المتوسط (انفجار)
MIN_VOLUME_ACCELERATION = 2.0   # تسارع تدفق السيولة بضعفين
MIN_CHANGE = 0.7                # الحد الأدنى لزخم الشمعة الأخيرة (%)
ALERT_COOLDOWN = 900            # تبريد 15 دقيقة لمنع التكرار المزعج
SYMBOLS_LIMIT = 250 

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

async def send_telegram(msg):
    if not bot: return
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        print("✅ تم إرسال التنبيه إلى تلغرام")
    except Exception as e:
        print(f"❌ فشل إرسال تلغرام: {e}")

# ====================== FETCH MOMENTUM SYMBOLS =====================
async def fetch_active_symbols(session, is_premarket):
    url = "https://scanner.tradingview.com/america/scan"
    sort_column = "premarket_change" if is_premarket else "change"
    
    # دمج فلتر القيمة السوقية (50 مليون إلى 1.5 مليار دولار) لاستهداف الأسهم خفيفة العائم (Low Float)
    payload = {
        "filter": [
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "market_cap_basic", "operation": "in_range", "right": [50000000, 1500000000]} 
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "volume", "premarket_change", "market_cap_basic"],
        "sort": {"sortBy": sort_column, "sortOrder": "desc"}
    }
    try:
        async with session.post(url, json=payload, timeout=15) as resp:
            data = await resp.json()
            symbols = []
            for item in data.get('data', []):
                d = item['d']
                if len(d) >= 3 and d[0]:
                    symbols.append(d[0])
            return symbols[:SYMBOLS_LIMIT]
    except Exception as e:
        print(f"❌ فشل سكنر الزخم من TradingView: {e}")
        return []

# ====================== LIVE VERIFICATION =======================
async def verify_live_price(session, symbol):
    if FINNHUB_API_KEY:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
        try:
            async with session.get(url, timeout=4) as resp:
                data = await resp.json()
                if "c" in data and data["c"] > 0: return data["c"]
        except: pass

    if POLYGON_API_KEY:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
        try:
            async with session.get(url, timeout=4) as resp:
                data = await resp.json()
                if "results" in data and len(data["results"]) > 0: return data["results"][0].get("c")
        except: pass

    if STOCKDATA_API_KEY:
        url = f"https://api.stockdata.org/v1/data/quote?symbols={symbol}&api_token={STOCKDATA_API_KEY}"
        try:
            async with session.get(url, timeout=4) as resp:
                data = await resp.json()
                if "data" in data and len(data["data"]) > 0: return data["data"][0].get("price")
        except: pass
    return None

# ====================== FETCH & ANALYZE ALL DATA ==================
async def fetch_all_data(symbols, is_premarket):
    if not symbols: return {}
    try:
        data = yf.download(tickers=symbols, period="2d", interval="5m", group_by='ticker', auto_adjust=True, threads=True, prepost=True, progress=False)
        results = {}
        for symbol in symbols:
            try:
                df = data if len(symbols) == 1 else data.get(symbol)
                if df is None or df.empty or len(df) < 5: continue
                
                last_date = df.index[-1].date()
                df_today = df[df.index.date == last_date]
                df_yesterday = df[df.index.date < last_date]
                
                if df_today.empty: continue
                
                current = df_today.iloc[-1]
                price = current["Close"]
                volume = current["Volume"]
                
                yesterday_close = df_yesterday["Close"].iloc[-1] if not df_yesterday.empty else df_today["Close"].iloc[0]
                
                if is_premarket:
                    # 🌅 حساب الزخم للبري ماركت بناءً على الفجوة السعرية من إغلاق أمس
                    price_change = ((price - yesterday_close) / yesterday_close) * 100
                    if len(df_today) >= 2:
                        avg_volume_pre = df_today["Volume"].iloc[:-1].mean()
                        if avg_volume_pre == 0 or pd.isna(avg_volume_pre): avg_volume_pre = 1000
                        volume_spike = volume / avg_volume_pre
                        volume_acceleration = volume / df_today["Volume"].iloc[-2] if df_today["Volume"].iloc[-2] > 0 else 1.5
                    else:
                        volume_spike = 3.5  
                        volume_acceleration = 2.0
                else:
                    # 🟢 حساب زخم الاختراقات اللحظية أثناء السوق الرسمي
                    price_change = ((price - df_today["Close"].iloc[-2]) / df_today["Close"].iloc[-2]) * 100 if len(df_today) > 1 else 0
                    avg_volume_10 = df["Volume"].iloc[-11:-1].mean()
                    volume_spike = volume / avg_volume_10 if avg_volume_10 > 0 else 1.0
                    volume_last_5 = df["Volume"].iloc[-6:-1].mean()
                    volume_acceleration = volume / volume_last_5 if volume_last_5 > 0 else 1.0
                
                sma20 = df["Close"].iloc[-20:].mean() if len(df) >= 20 else price
                
                results[symbol] = {
                    "price": price, "volume": volume, "volume_spike": volume_spike,
                    "volume_acceleration": volume_acceleration, "price_change": price_change, "sma20": sma20
                }
            except: continue
        return results
    except Exception as e:
        print(f"❌ خطأ رادار ياهو: {e}")
        return {}

# ====================== MAIN LOOP ===============================
async def main_loop():
    global last_reset_date, last_premarket_sent, last_market_open_sent
    await send_telegram("🐉 *M60 Ultimate Momentum Sniper - نظام صيد الأسهم خفيفة العائم يعمل بكامل طاقته الآن*")

    while True:
        try:
            now_makkah = datetime.now(MAKKAH_TZ)
            now_ny = datetime.now(NY_TZ)
            
            is_premarket = now_ny.hour < 9 or (now_ny.hour == 9 and now_ny.minute < 30) or now_ny.hour >= 16
            
            if is_premarket:
                abs_min_volume = 3000  # حد مرن لشموع الفجر للأسهم خفيفة العائم
                market_status = "بري ماركت 🌅" if now_ny.hour < 12 else "أفتر ماركت 🌙"
            else:
                abs_min_volume = 35000 # حد قوي يضمن استمرار السيولة واختراق السوق الرسمي
                market_status = "السوق الرسمي 🟢"

            if now_makkah.hour == 11 and now_makkah.minute == 0 and not last_premarket_sent:
                await send_telegram("🌅 *بداية فحص زخم البري ماركت (11 ص مكة)*")
                last_premarket_sent = True
            if now_makkah.hour == 16 and now_makkah.minute == 30 and not last_market_open_sent:
                await send_telegram("🔔 *افتتاح قناص الزخم للسوق الرسمي (4:30 م مكة)*")
                last_market_open_sent = True
            if now_makkah.hour == 0 and now_makkah.minute == 0:
                last_premarket_sent = last_market_open_sent = False

            if now_makkah.date() != last_reset_date:
                alert_counters.clear()
                last_reset_date = now_makkah.date()

            async with aiohttp.ClientSession() as session:
                symbols = await fetch_active_symbols(session, is_premarket)
                if not symbols:
                    await asyncio.sleep(20)
                    continue

                all_data = await fetch_all_data(symbols, is_premarket)
                for symbol, data in all_data.items():
                    
                    is_potential_explosion = (
                        MIN_PRICE <= data["price"] <= MAX_PRICE and
                        data["volume"] >= abs_min_volume and 
                        data["volume_spike"] >= MIN_VOLUME_SPIKE and
                        data["volume_acceleration"] >= MIN_VOLUME_ACCELERATION and
                        data["price_change"] > MIN_CHANGE and
                        data["price"] > data["sma20"]
                    )

                    if is_potential_explosion:
                        live_price = await verify_live_price(session, symbol)
                        final_price = live_price if live_price else data["price"]
                        
                        if final_price > data["sma20"] and can_alert(symbol):
                            alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                            
                            target1, target2 = final_price * 1.05, final_price * 1.10
                            stop_loss = final_price * 0.96

                            msg = (
                                f"🚀 *قناص الزخم: سهم خفيف العائم ينفجر*\n"
                                f"الفترة الحالية: {market_status}\n\n"
                                f"📊 الرمز: `{symbol}`\n"
                                f"💰 السعر الحالي: `${final_price:.2f}`\n"
                                f"📈 حجم الشمعة: `{data['volume']:,}` سهم\n"
                                f"🔥 مضاعف السيولة: `{data['volume_spike']:.1f}x` أضعاف الطبيعي\n"
                                f"⚡ تسارع التدفق: `{data['volume_acceleration']:.1f}x`\n"
                                f"📈 صعود الزخم الحقيقي: `+{data['price_change']:.2f}%`\n"
                                f"🎯 الأهداف المقترحة: `{target1:.2f}` ← `{target2:.2f}`\n"
                                f"🛑 وقف الخسارة الصارم: `{stop_loss:.2f}`\n"
                                f"🔢 تنبيه رقم #{alert_counters[symbol]}\n\n"
                                f"⚠️ استراتيجية (Low-Float Full Session) مُفعّلة"
                            )
                            await send_telegram(msg)
                            await asyncio.sleep(1)

                print(f"⏳ دورة فحص زخم كاملة ناجحة للأسهم الخفيفة. وضع السوق: {market_status}")
                await asyncio.sleep(120)

        except Exception as e:
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
