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
import numpy as np
from tvkit import TVClient  # TradingView Client

# ================= FAKE WEB SERVER (for Render) =================
web_app = Flask('')

@web_app.route('/')
def home():
    return "M60bot is running!"

def run_web_server():
    web_app.run(host='0.0.0.0', port=10000)

# ================= START WEB SERVER IN BACKGROUND =================
Thread(target=run_web_server, daemon=True).start()

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# ================= ENV =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")  # للاستخدام الاحتياطي فقط

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing Telegram config")

bot = Bot(token=TOKEN)

# ================= SETTINGS =================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
MIN_MOVE = 1.0
MIN_VOLUME = 50000
COOLDOWN = 120
MIN_REL_VOL = 1.2

# إعدادات منفصلة للبري ماركت والآفتر ماركت (أخف)
PREMARKET_MIN_VOLUME = 20000
PREMARKET_MIN_MOVE = 0.5
PREMARKET_MIN_REL_VOL = 0.8

last_alert = {}
alert_counters = {}
alert_history = {}

# ================= TIME =================
def ny():
    return datetime.now(pytz.timezone("America/New_York"))

def get_session():
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

# ================= TRADINGVIEW (المصدر الرئيسي) =================
def fetch_tradingview_stocks():
    """جلب الأسهم من TradingView باستخدام tvkit"""
    print("📡 [TradingView] جاري جلب الأسهم...")
    
    # قائمة تجريبية من الأسهم المعروفة
    test_symbols = ["AAPL", "TSLA", "NVDA", "AMD", "AMZN", "MSFT", "GOOGL", "META", "NFLX", "INTC"]
    
    stocks = []
    
    try:
        # إنشاء عميل TradingView
        client = TVClient()
        
        for symbol in test_symbols:
            try:
                print(f"📡 [TradingView] جاري جلب {symbol}...")
                
                # جلب البيانات من TradingView
                # ملاحظة: tvkit يستخدم صيغة مختلفة للرموز، نضيف "NASDAQ:" أو "NYSE:" حسب الحاجة
                # للتجربة، نستخدم الصيغة المبسطة
                data = client.get_quote(symbol)
                
                if not data:
                    print(f"⚠️ {symbol}: لا توجد بيانات")
                    continue
                
                # استخراج البيانات
                price = data.get('close', 0)
                volume = data.get('volume', 0)
                change = data.get('change', 0)
                
                if price <= 0 or volume <= 0:
                    print(f"⚠️ {symbol}: سعر أو حجم غير صحيح (price={price}, volume={volume})")
                    continue
                
                stocks.append({
                    "ticker": symbol,
                    "close": price,
                    "change": change,
                    "volume": volume
                })
                print(f"✅ {symbol}: ${price:.2f}, {change:.2f}%, حجم: {volume:,}")
                
            except Exception as e:
                print(f"⚠️ {symbol}: خطأ: {type(e).__name__}: {e}")
                continue
        
        print(f"📡 [TradingView] تم جلب {len(stocks)} سهماً")
        return stocks
        
    except Exception as e:
        print(f"⚠️ [TradingView] خطأ في الاتصال: {e}")
        # في حال فشل TradingView، نستخدم Yahoo كنسخة احتياطية
        print("📡 [TradingView] فشل الاتصال، استخدام Yahoo كنسخة احتياطية...")
        return fetch_yahoo_fallback()

def fetch_yahoo_fallback():
    """نسخة احتياطية باستخدام Yahoo"""
    print("📡 [Yahoo - Fallback] جاري جلب الأسهم...")
    
    test_symbols = ["AAPL", "TSLA", "NVDA", "AMD", "AMZN", "MSFT", "GOOGL", "META", "NFLX", "INTC"]
    
    stocks = []
    for symbol in test_symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                continue
                
            data = response.json()
            if not data.get('chart', {}).get('result'):
                continue
                
            meta = data['chart']['result'][0].get('meta', {})
            price = meta.get('regularMarketPrice', 0)
            volume = meta.get('regularMarketVolume', 0)
            
            if price <= 0 or volume <= 0:
                continue
            
            prev_close = meta.get('regularMarketPreviousClose', price)
            change = ((price - prev_close) / prev_close) * 100 if prev_close else 0
            
            stocks.append({
                "ticker": symbol,
                "close": price,
                "change": change,
                "volume": volume
            })
            print(f"✅ {symbol}: ${price:.2f}, {change:.2f}%, حجم: {volume:,}")
            
        except Exception as e:
            continue
    
    print(f"📡 [Yahoo - Fallback] تم جلب {len(stocks)} سهماً")
    return stocks

# ================= VOLUME RATIO =================
def calculate_rel_vol(volume):
    """حساب الحجم النسبي (تقديري)"""
    avg_volume = 50000
    return volume / avg_volume if avg_volume > 0 else 1.0

# ================= FILTER =================
def valid(stock, is_premarket=False):
    try:
        price = float(stock.get("close") or 0)
        change = float(stock.get("change") or 0)
        vol = float(stock.get("volume") or 0)

        if price < MIN_PRICE or price > MAX_PRICE:
            return False
        
        if is_premarket:
            if vol < PREMARKET_MIN_VOLUME or change < PREMARKET_MIN_MOVE:
                return False
        else:
            if vol < MIN_VOLUME or change < MIN_MOVE:
                return False

        return True
    except:
        return False

# ================= ENGINE =================
def detect(stocks, is_premarket=False):
    alerts = []

    for stock in stocks:
        if not valid(stock, is_premarket):
            continue

        sym = stock.get("ticker")
        price = float(stock.get("close") or 0)
        volume = float(stock.get("volume") or 0)
        change = float(stock.get("change") or 0)

        rel_vol = calculate_rel_vol(volume)

        if is_premarket:
            if rel_vol < PREMARKET_MIN_REL_VOL:
                continue
        else:
            if rel_vol < MIN_REL_VOL:
                continue

        now = ny().timestamp()
        if now - last_alert.get(sym, 0) < COOLDOWN:
            continue

        last_alert[sym] = now
        alert_counters[sym] = alert_counters.get(sym, 0) + 1

        target1 = price * 1.05
        target2 = price * 1.10
        target3 = price * 1.15
        stop_loss = price * 0.95

        if change > 3.0 and volume > 500000:
            strength = "💥 قوية جداً"
        elif change > 2.0 and volume > 200000:
            strength = "🚀 قوية"
        else:
            strength = "📈 متوسطة"

        alerts.append((sym, price, change, rel_vol, 1.0, alert_counters[sym], target1, target2, target3, stop_loss, strength))

    return alerts

# ================= ALERT FORMAT =================
async def send_alert(sym, price, move, rel_vol, mom_acc, alert_num, t1, t2, t3, sl, strength):
    now = ny().strftime("%H:%M:%S")
    
    if move > 3.0 and rel_vol > 2.0:
        move_type = "🚀 انفجار قوي"
    elif move > 2.0 and rel_vol > 1.5:
        move_type = "📈 اختراق إيجابي"
    else:
        move_type = "📈 تحرك"

    msg = (
        f"📊 *{sym} — {now}* 📊\n\n"
        f"🔹 *السعر:* `${price:.2f}`\n"
        f"🔹 *الارتفاع:* `+{move:.2f}%`\n"
        f"🔹 *الحجم النسبي:* `{rel_vol:.1f}x`\n"
        f"🔹 *التنبيه:* `{alert_num} مرة`\n\n"
        f"🎯 *الأهداف:*\n"
        f"  • مقاومة 1: `{t1:.3f}`\n"
        f"  • مقاومة 2: `{t2:.3f}`\n"
        f"  • دعم: `{sl:.3f}`\n\n"
        f"📌 *توصية:* {strength}"
    )
    await send(msg)

# ================= MAIN =================
async def main():
    print(f"🕒 الوقت: {ny().strftime('%H:%M:%S')}")
    print(f"📌 الجلسة: {get_session()}")
    print(f"💰 الفئة السعرية: ${MIN_PRICE} - ${MAX_PRICE}")
    print(f"🔍 المصدر: TradingView (مع Yahoo كنسخة احتياطية)")

    await send("📊 *M60 Hunter - TradingView*")

    while True:
        current_session = get_session()
        print(f"\n🔄 دورة جديدة - {current_session}")
        
        # ===== جلب الأسهم من TradingView =====
        stocks = fetch_tradingview_stocks()
        
        if not stocks:
            print("⚠️ لم يتم جلب أي أسهم، إعادة المحاولة...")
            await asyncio.sleep(30)
            continue
        
        # ===== تطبيق الشروط =====
        is_premarket = (current_session == "premarket" or current_session == "afterhours")
        signals = detect(stocks, is_premarket)
        
        print(f"✅ signals: {len(signals)}")
        
        for s in signals:
            await send_alert(*s)
            await asyncio.sleep(1)
        
        # ===== ننتظر 30 ثانية قبل الدورة التالية =====
        print(f"⏳ انتظار 30 ثانية...")
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
