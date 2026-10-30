import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
import yfinance as yf
from flask import Flask
import threading

# ==================== الإعدادات ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLYGON_KEY = os.environ.get("POLYGON_KEY")

WATCHLIST = ["SPY", "QQQ"]
NY_TZ = pytz.timezone('America/New_York')
LAST_REPORT_DATE = None 

# ==================== الخادم الوهمي ====================
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Bot is running!", 200
def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ==================== دوال البيانات ====================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"خطأ تلقرام: {e}")

def get_polygon_data(symbol, interval="15"):
    """نجلب بيانات 15 دقيقة (لتحديد الاتجاه بدقة ومنع الضوضاء)"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (600 * 60 * 1000) # آخر 10 ساعات
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{interval}/minute/{start_time}/{end_time}?apiKey={POLYGON_KEY}&limit=50"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('results'):
            df = pd.DataFrame(data['results'])
            df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'time'}, inplace=True)
            return df
        return None
    except:
        return None

def get_spx_real_data():
    try:
        df = yf.download("^GSPC", period="10d", interval="1d", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df
    except:
        return None

def calculate_indicators(df):
    if df is None or len(df) < 20:
        return None
    # المتوسطات و VWAP
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
    df['VWAP'] = (df['Typical_Price'] * df['volume']).cumsum() / df['volume'].cumsum()
    
    # ATR لحساب الأهداف
    df['TR'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), 
                          abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# ==================== التقرير الصباحي ====================
def send_morning_report():
    df = get_spx_real_data()
    if df is None or len(df) < 5:
        send_telegram("⚠️ <b>فشل جلب بيانات SPX.</b>")
        return

    current_close = df.iloc[-1]['close']
    high = df.iloc[-1]['high']
    low = df.iloc[-1]['low']
    
    pivot = (high + low + current_close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)

    msg = f"""
🌅 <b>التقرير الصباحي | S&P 500 (SPX)</b>
<b>إغلاق الأمس:</b> {current_close:.2f}

🔴 <b>مقاومة 2:</b> {r2:.2f}
🔴 <b>مقاومة 1:</b> {r1:.2f}
⚪ <b>نقطة الارتكاز:</b> {pivot:.2f}
🟢 <b>دعم 1:</b> {s1:.2f}
🟢 <b>دعم 2:</b> {s2:.2f}

🎯 <i>البوت سيحدد الاتجاه، وسيرسل تنبيهاً عند الاقتراب من هذه المستويات، مع خطة عمل واضحة.</i>
"""
    send_telegram(msg)

# ==================== محرك القرار (الاتجاه + الاقتراب + التأكيد) ====================
def analyze_symbol(symbol):
    # 1. تحديد الاتجاه على فاصل 15 دقيقة
    df = get_polygon_data(symbol, interval="15")
    if df is None or len(df) < 20:
        return
    df = calculate_indicators(df)
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last['close']
    atr = last['ATR']
    
    # تحديد الاتجاه العام
    trend = "NEUTRAL"
    if last['close'] > last['VWAP'] and last['EMA9'] > last['EMA21']:
        trend = "BULLISH"
    elif last['close'] < last['VWAP'] and last['EMA9'] < last['EMA21']:
        trend = "BEARISH"

    # 2. تحديد مناطق القرار (المقاومة والدعم) من آخر 20 شمعة
    resistance = df['high'].iloc[-21:-1].max()
    support = df['low'].iloc[-21:-1].min()
    
    # حساب المسافة
    dist_to_res = abs(resistance - price)
    dist_to_sup = abs(price - support)
    
    # إذا كان السعر قريباً من المقاومة (على مسافة 0.15% أو أقل)
    if dist_to_res <= (price * 0.0015):
        msg = f"""
⚠️ <b>اقتراب من مقاومة | {symbol}</b>
<b>السعر:</b> {price:.2f}
<b>المقاومة:</b> {resistance:.2f}
<b>الاتجاه العام (15m):</b> {trend}

📉 <b>خطة العمل (إذا فشل الاختراق):</b>
ادخل <b>PUT</b> إذا رأيت شمعة رفض حمراء (ذيل علوي طويل).
🎯 الأهداف: {price - atr:.2f} / {price - (atr*2):.2f} / {price - (atr*3):.2f}
🛑 الوقف: {resistance + (atr*0.5):.2f}

📈 <b>خطة العمل (إذا اخترق بقوة):</b>
ادخل <b>CALL</b> إذا أغلق شمعة 15 دقيقة فوق {resistance:.2f} بحجم كبير.
🎯 الأهداف: {price + atr:.2f} / {price + (atr*2):.2f} / {price + (atr*3):.2f}
🛑 الوقف: {resistance - (atr*0.5):.2f}

⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)
        print(f"⚠️ Approaching Resistance: {symbol}")

    # إذا كان السعر قريباً من الدعم
    elif dist_to_sup <= (price * 0.0015):
        msg = f"""
⚠️ <b>اقتراب من دعم | {symbol}</b>
<b>السعر:</b> {price:.2f}
<b>الدعم:</b> {support:.2f}
<b>الاتجاه العام (15m):</b> {trend}

📈 <b>خطة العمل (إذا ارتد):</b>
ادخل <b>CALL</b> إذا رأيت شمعة ارتداد خضراء (ذيل سفلي طويل).
🎯 الأهداف: {price + atr:.2f} / {price + (atr*2):.2f} / {price + (atr*3):.2f}
🛑 الوقف: {support - (atr*0.5):.2f}

📉 <b>خطة العمل (إذا كسر بقوة):</b>
ادخل <b>PUT</b> إذا أغلق شمعة 15 دقيقة تحت {support:.2f} بحجم كبير.
🎯 الأهداف: {price - atr:.2f} / {price - (atr*2):.2f} / {price - (atr*3):.2f}
🛑 الوقف: {support + (atr*0.5):.2f}

⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)
        print(f"⚠️ Approaching Support: {symbol}")

# ==================== التشغيل ====================
def main():
    global LAST_REPORT_DATE
    threading.Thread(target=run_web_server, daemon=True).start()
    
    print("🚀 البوت يعمل (نظام تأكيد الاتجاه)...")
    send_telegram("✅ <b>تم تشغيل النظام المتقدم</b>\nالبوت يحدد الاتجاه ويرسل خطط العمل عند الاقتراب من المقاومات والدعوم.")
    
    send_morning_report()
    LAST_REPORT_DATE = datetime.now(NY_TZ).strftime('%Y-%m-%d')
    
    while True:
        now = datetime.now(NY_TZ)
        
        if now.weekday() < 5 and now.hour == 9 and now.minute == 0:
            today_str = now.strftime('%Y-%m-%d')
            if LAST_REPORT_DATE != today_str:
                send_morning_report()
                LAST_REPORT_DATE = today_str

        if now.weekday() < 5 and (9 <= now.hour < 16): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(5)
        else:
            print(f"⏳ السوق مغلق ({now.strftime('%H:%M')} NY)")
        
        time.sleep(60)

if __name__ == "__main__":
    main()
