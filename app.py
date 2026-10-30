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

# ==================== جلب المفاتيح ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLYGON_KEY = os.environ.get("POLYGON_KEY")

# ==================== قائمة المراقبة ====================
WATCHLIST = ["SPY", "QQQ"]
NY_TZ = pytz.timezone('America/New_York')
LAST_REPORT_DATE = None 

# ==================== خادم ويب وهمي لإرضاء Render ====================
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Bot is running!", 200
def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ==================== دوال مساعدة ====================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"خطأ تلقرام: {e}")

def get_polygon_data(symbol, interval="5"):
    """جلب بيانات 5 دقائق لالتقاط الحركة السريعة"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (240 * 60 * 1000) # آخر 4 ساعات
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
    """جلب بيانات SPX للتقرير الصباحي"""
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
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
    df['VWAP'] = (df['Typical_Price'] * df['volume']).cumsum() / df['volume'].cumsum()
    df['TR'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), 
                          abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def get_trend_30m(symbol):
    """فلتر الاتجاه: جلب بيانات 30 دقيقة لتحديد الاتجاه العام"""
    df = get_polygon_data(symbol, interval="30")
    if df is None or len(df) < 5:
        return "NEUTRAL"
    df = calculate_indicators(df)
    if df is None:
        return "NEUTRAL"
    
    last = df.iloc[-1]
    if last['close'] > last['VWAP'] and last['EMA9'] > last['EMA21']:
        return "BULLISH"
    elif last['close'] < last['VWAP'] and last['EMA9'] < last['EMA21']:
        return "BEARISH"
    return "NEUTRAL"

# ==================== التقرير الصباحي ====================
def send_morning_report():
    df = get_spx_real_data()
    if df is None or len(df) < 5:
        send_telegram("⚠️ <b>فشل جلب بيانات SPX الحقيقية.</b>")
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
<i>(بيانات حقيقية)</i>

<b>إغلاق الأمس:</b> {current_close:.2f}

📊 <b>المستويات المهمة لليوم:</b>
🔴 <b>مقاومة 2:</b> {r2:.2f}
🔴 <b>مقاومة 1:</b> {r1:.2f}
⚪ <b>نقطة الارتكاز:</b> {pivot:.2f}
🟢 <b>دعم 1:</b> {s1:.2f}
🟢 <b>دعم 2:</b> {s2:.2f}

🎯 <b>الاستراتيجية:</b>
البوت سيراقب هذه المستويات. إذا اقترب السعر من مقاومة ولمخترقها بعد، سيرسل تنبيه (PUT). وإذا اقترب من دعم، سيرسل تنبيه (CALL).
"""
    send_telegram(msg)

# ==================== محرك الإشارات الاستباقي ====================
def analyze_symbol(symbol):
    # 1. فلتر الاتجاه العام (30 دقيقة)
    trend = get_trend_30m(symbol)
    
    # 2. بيانات التنفيذ (5 دقائق)
    df = get_polygon_data(symbol, interval="5")
    if df is None or len(df) < 20:
        return
    df = calculate_indicators(df)
    if df is None:
        return

    last = df.iloc[-1]
    current_price = last['close']
    current_volume = last['volume']
    avg_volume = df['volume'].iloc[-10:-1].mean()
    atr = last['ATR']
    
    # تحديد مستويات المقاومة والدعم من آخر ساعتين (على فاصل 5 دقائق)
    recent_high = df['high'].iloc[-24:-1].max()
    recent_low = df['low'].iloc[-24:-1].min()
    
    # المسافة من المقاومة والدعم
    dist_to_res = abs(recent_high - current_price)
    dist_to_sup = abs(current_price - recent_low)
    
    # إذا كان السعر قريباً جداً من المقاومة (على مسافة 0.2% أو أقل) ولم يخترقها
    threshold = current_price * 0.002 
    
    if dist_to_res <= threshold and current_price < recent_high:
        # إشارة استباقية (PUT) - فشل اختراق
        if trend != "BULLISH": # لا نبيع إذا كان الاتجاه العام صاعداً بقوة
            stop_loss = recent_high + (atr * 0.5)
            t1 = current_price - (atr * 1.0)
            t2 = current_price - (atr * 2.0)
            t3 = current_price - (atr * 3.0)
            
            msg = f"""
⚠️ <b>تنبيه استباقي: اقتراب من مقاومة | {symbol}</b>
<b>السعر الحالي:</b> {current_price:.2f}
<b>المقاومة:</b> {recent_high:.2f}
<b>الاتجاه العام (30m):</b> {trend}

🔴 <b>احتمال فشل الاختراق ← إشارة PUT:</b>
🎯 <b>الأهداف:</b> {t1:.2f} / {t2:.2f} / {t3:.2f}
🛑 <b>وقف الخسارة:</b> {stop_loss:.2f}

<b>الخطة:</b> راقب السعر. إذا فشل في اختراق {recent_high:.2f}، ادخل PUT.
⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')}
⚠️ <i>ليست نصيحة مالية</i>
"""
            send_telegram(msg)
            print(f"✅ Alert PUT: {symbol}")

    # إذا كان السعر قريباً جداً من الدعم ولم يكسرها
    elif dist_to_sup <= threshold and current_price > recent_low:
        if trend != "BEARISH": 
            stop_loss = recent_low - (atr * 0.5)
            t1 = current_price + (atr * 1.0)
            t2 = current_price + (atr * 2.0)
            t3 = current_price + (atr * 3.0)
            
            msg = f"""
⚠️ <b>تنبيه استباقي: اقتراب من دعم | {symbol}</b>
<b>السعر الحالي:</b> {current_price:.2f}
<b>الدعم:</b> {recent_low:.2f}
<b>الاتجاه العام (30m):</b> {trend}

🟢 <b>احتمال الارتداد ← إشارة CALL:</b>
🎯 <b>الأهداف:</b> {t1:.2f} / {t2:.2f} / {t3:.2f}
🛑 <b>وقف الخسارة:</b> {stop_loss:.2f}

<b>الخطة:</b> راقب السعر. إذا ارتد من {recent_low:.2f}، ادخل CALL.
⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')}
⚠️ <i>ليست نصيحة مالية</i>
"""
            send_telegram(msg)
            print(f"✅ Alert CALL: {symbol}")

# ==================== التشغيل الرئيسي ====================
def main():
    global LAST_REPORT_DATE
    
    threading.Thread(target=run_web_server, daemon=True).start()
    
    print("🚀 محرك الإشارات الاستباقي يعمل...")
    send_telegram("✅ <b>تم تشغيل نظام التنبيهات الاستباقية</b>\nالبوت يراقب اقتراب السعر من المقاومات والدعوم.")
    
    send_morning_report()
    LAST_REPORT_DATE = datetime.now(NY_TZ).strftime('%Y-%m-%d')
    
    while True:
        now = datetime.now(NY_TZ)
        
        if now.weekday() < 5 and now.hour == 9 and now.minute == 0:
            today_str = now.strftime('%Y-%m-%d')
            if LAST_REPORT_DATE != today_str:
                send_morning_report()
                LAST_REPORT_DATE = today_str

        # التداول فقط في أول ساعتين ونصف (لتجنب عشوائية آخر الجلسة)
        if now.weekday() < 5 and (9 <= now.hour < 12): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(3)
        else:
            print(f"⏳ خارج وقت التداول الأمثل ({now.strftime('%H:%M')} NY)")
        
        time.sleep(60)

if __name__ == "__main__":
    main()
