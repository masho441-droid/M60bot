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

# ==================== دوال البوت ====================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"خطأ تلقرام: {e}")

def get_polygon_data(symbol):
    """جلب البيانات اللحظية من Polygon لـ SPY و QQQ"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (240 * 60 * 1000) # آخر 4 ساعات
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/5/minute/{start_time}/{end_time}?apiKey={POLYGON_KEY}&limit=50"
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
    """جلب بيانات SPX الحقيقية من ياهو فاينانس (بدون مفتاح)"""
    try:
        df = yf.download("^GSPC", period="10d", interval="1d", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        print(f"خطأ في جلب SPX: {e}")
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
    df['Vol_Avg'] = df['volume'].rolling(window=10).mean()
    return df

# ==================== التقرير الصباحي (SPX حقيقي) ====================
def send_morning_report():
    df = get_spx_real_data()
    if df is None or len(df) < 5:
        send_telegram("⚠️ <b>فشل جلب بيانات SPX الحقيقية.</b>")
        return

    current_close = df.iloc[-1]['close']
    prev_close = df.iloc[-2]['close']
    high = df.iloc[-1]['high']
    low = df.iloc[-1]['low']
    high_5d = df['high'].max()
    low_5d = df['low'].min()

    # Pivot Points
    pivot = (high + low + current_close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    r3 = high + 2 * (pivot - low)
    s3 = low - 2 * (high - pivot)

    # Fibonacci
    diff = high - low
    fib_618 = high - (diff * 0.618)
    fib_500 = high - (diff * 0.500)

    trend = "صاعد 🟢" if current_close > prev_close else "هابط 🔴"
    
    msg = f"""
🌅 <b>التقرير الصباحي المفصل | S&P 500 (SPX)</b>
<i>(بيانات حقيقية من ^GSPC)</i>

<b>إغلاق الأمس:</b> {current_close:.2f}
<b>الاتجاه العام:</b> {trend}
<b>نطاق 5 أيام:</b> {low_5d:.2f} - {high_5d:.2f}

📊 <b>خريطة المستويات الكاملة:</b>

🔴 <b>مقاومات (أهداف الكول):</b>
• مقاومة 3: {r3:.2f}
• مقاومة 2: {r2:.2f}
• مقاومة 1: {r1:.2f}
• فيبوناتشي 61.8%: {fib_618:.2f}

⚪ <b>نقطة الارتكاز (Pivot):</b> {pivot:.2f}

🟢 <b>دعوم (أهداف البوت):</b>
• دعم 1: {s1:.2f}
• دعم 2: {s2:.2f}
• دعم 3: {s3:.2f}
• فيبوناتشي 50%: {fib_500:.2f}

🎯 <b>خطة التداول المرنة:</b>
1️⃣ <b>إذا ارتد السعر من {s1:.2f}:</b> استهدف <b>{pivot:.2f}</b> ثم <b>{r1:.2f}</b> (Call).
2️⃣ <b>إذا كسر السعر {s2:.2f}:</b> استهدف <b>{s3:.2f}</b> (Put)، وراقب فيبوناتشي {fib_500:.2f}.

⚠️ <i>ليست نصيحة مالية.</i>
⏱️ {datetime.now(NY_TZ).strftime('%Y-%m-%d')}
"""
    send_telegram(msg)
    print("✅ تم إرسال التقرير الصباحي (SPX حقيقي)")

# ==================== محرك الإشارات اللحظي ====================
def analyze_symbol(symbol):
    df = get_polygon_data(symbol)
    if df is None or len(df) < 20:
        return
    df = calculate_indicators(df)
    if df is None:
        return

    last = df.iloc[-1]
    prev = df.iloc[-2]
    current_price = last['close']
    current_volume = last['volume']
    avg_volume = last['Vol_Avg']
    vwap = last['VWAP']
    atr = last['ATR']
    recent_high = df['high'].iloc[-4:-1].max()
    recent_low = df['low'].iloc[-4:-1].min()
    
    reasons = []
    score = 0

    if current_price > vwap:
        score += 20
        reasons.append("السعر فوق VWAP (سيطرة المشترين)")
        if last['EMA9'] > last['EMA21']:
            score += 15
            reasons.append("EMA9 فوق EMA21 (اتجاه صاعد)")
    elif current_price < vwap:
        score -= 20
        reasons.append("السعر تحت VWAP (سيطرة البائعين)")
        if last['EMA9'] < last['EMA21']:
            score -= 15
            reasons.append("EMA9 تحت EMA21 (اتجاه هابط)")

    if 45 < last['RSI'] < 75 and score > 0:
        score += 15
        reasons.append(f"RSI إيجابي ({last['RSI']:.1f})")
    elif 25 < last['RSI'] < 55 and score < 0:
        score -= 15
        reasons.append(f"RSI سلبي ({last['RSI']:.1f})")
    elif last['RSI'] >= 80:
        score -= 30
        reasons.append("تحذير: RSI في ذروة الشراء!")
    elif last['RSI'] <= 20:
        score += 30
        reasons.append("تحذير: RSI في ذروة البيع!")

    if current_volume > (avg_volume * 1.5):
        score += 20 if score > 0 else -20
        reasons.append(f"انفجار في الحجم ({current_volume/avg_volume:.1f}x)")

    if current_price > recent_high and score > 0:
        score += 30
        reasons.append("اختراق قمة الـ 15 دقيقة")
    elif current_price < recent_low and score < 0:
        score -= 30
        reasons.append("كسر قاع الـ 15 دقيقة")

    display_name = symbol.replace("I:", "")
    
    if score >= 70:
        target1 = current_price + (atr * 1.5)
        target2 = current_price + (atr * 3.0)
        stop_loss = current_price - (atr * 1.0)
        msg = f"""
🟢 <b>إشارة CALL عالية الدقة | {display_name}</b>
<b>السعر:</b> {current_price:.2f}
<b>درجة الثقة:</b> {min(score, 100)}/100
🎯 <b>الأهداف:</b> {target1:.2f} / {target2:.2f}
🛑 <b>وقف الخسارة:</b> {stop_loss:.2f}
<b>الأسباب:</b>
{chr(10).join(['• ' + r for r in reasons])}
⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)
    elif score <= -70:
        target1 = current_price - (atr * 1.5)
        target2 = current_price - (atr * 3.0)
        stop_loss = current_price + (atr * 1.0)
        msg = f"""
🔴 <b>إشارة PUT عالية الدقة | {display_name}</b>
<b>السعر:</b> {current_price:.2f}
<b>درجة الثقة:</b> {min(abs(score), 100)}/100
🎯 <b>الأهداف:</b> {target1:.2f} / {target2:.2f}
🛑 <b>وقف الخسارة:</b> {stop_loss:.2f}
<b>الأسباب:</b>
{chr(10).join(['• ' + r for r in reasons])}
⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)

# ==================== التشغيل الرئيسي ====================
def main():
    global LAST_REPORT_DATE
    
    threading.Thread(target=run_web_server, daemon=True).start()
    
    print("🚀 محرك القناص الاحترافي يعمل...")
    send_telegram("✅ <b>تم تشغيل محرك القناص الاحترافي</b>\nالمراقبة: SPY, QQQ\nالتقرير الصباحي: SPX حقيقي.")
    
    send_morning_report()
    LAST_REPORT_DATE = datetime.now(NY_TZ).strftime('%Y-%m-%d')
    
    while True:
        now = datetime.now(NY_TZ)
        
        if now.weekday() < 5 and now.hour == 9 and now.minute == 0:
            today_str = now.strftime('%Y-%m-%d')
            if LAST_REPORT_DATE != today_str:
                send_morning_report()
                LAST_REPORT_DATE = today_str

        if now.weekday() < 5 and (10 <= now.hour < 16): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(2)
        else:
            print(f"⏳ السوق مغلق ({now.strftime('%H:%M')} NY)")
        
        time.sleep(60)

if __name__ == "__main__":
    main()
