import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from flask import Flask
import threading

# ==================== جلب المفاتيح من Render ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLYGON_KEY = os.environ.get("POLYGON_KEY")

# ==================== التركيز على 3 رموز ====================
WATCHLIST = ["I:SPX", "SPY", "QQQ"]
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
    """جلب البيانات اللحظية"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (120 * 60 * 1000) 
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{start_time}/{end_time}?apiKey={POLYGON_KEY}&limit=50"
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

def get_last_closed_daily_data(symbol):
    """جلب بيانات الجلسة المغلقة السابقة (للتقرير)"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (10 * 24 * 60 * 60 * 1000) 
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_time}/{end_time}?apiKey={POLYGON_KEY}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('results'):
            df = pd.DataFrame(data['results'])
            df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
            return df
        return None
    except:
        return None

def calculate_indicators(df):
    if df is None or len(df) < 20:
        return None
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['Vol_Avg'] = df['volume'].rolling(window=20).mean()
    return df

def send_morning_report():
    df = get_last_closed_daily_data("I:SPX")
    if df is None or len(df) < 2:
        send_telegram("⚠️ <b>فشل جلب بيانات التقرير.</b>\nتأكد أن المفتاح يدعم المؤشر I:SPX.")
        return

    prev_day = df.iloc[-1]
    prev_close = prev_day['close']
    high = prev_day['high']
    low = prev_day['low']
    
    pivot = (high + low + prev_close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)

    trend = "صاعد 🟢" if prev_close > df.iloc[-2]['close'] else "هابط 🔴"
    
    msg = f"""
🌅 <b>التقرير الصباحي | S&P 500 (SPX)</b>

<b>إغلاق الجلسة السابقة:</b> {prev_close:.2f}
<b>الاتجاه المتوقع:</b> {trend}

📊 <b>المستويات المهمة لليوم:</b>
🔴 <b>مقاومة 2:</b> {r2:.2f}
🔴 <b>مقاومة 1:</b> {r1:.2f}
⚪ <b>نقطة الارتكاز:</b> {pivot:.2f}
🟢 <b>دعم 1:</b> {s1:.2f}
🟢 <b>دعم 2:</b> {s2:.2f}

🎯 <b>خطة التداول المقترحة:</b>
• إذا اخترق السعر <b>{r1:.2f}</b> بحجم قوي ← استهدف <b>{r2:.2f}</b> (Call).
• إذا كسر السعر <b>{s1:.2f}</b> بحجم قوي ← استهدف <b>{s2:.2f}</b> (Put).

⚠️ <i>ليست نصيحة مالية. راقب السيولة عند التنفيذ.</i>
⏱️ {datetime.now(NY_TZ).strftime('%Y-%m-%d')}
"""
    send_telegram(msg)

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
    
    reasons = []
    score = 0

    if last['EMA9'] > last['EMA21'] and prev['EMA9'] <= prev['EMA21']:
        score += 30
        reasons.append("تقاطع EMA9 فوق EMA21 (صعود)")
    elif last['EMA9'] < last['EMA21']:
        score -= 20
        reasons.append("EMA9 تحت EMA21 (هبوط)")

    if 40 < last['RSI'] < 70:
        score += 15
        reasons.append(f"RSI صحي ({last['RSI']:.1f})")
    elif last['RSI'] >= 70:
        score += 10
        reasons.append(f"RSI في ذروة الشراء ({last['RSI']:.1f})")
    elif last['RSI'] < 30:
        score -= 10
        reasons.append(f"RSI في ذروة البيع ({last['RSI']:.1f})")

    if current_volume > (avg_volume * 1.5):
        score += 25
        reasons.append(f"انفجار في الحجم ({current_volume/avg_volume:.1f}x)")

    if current_price > prev['high']:
        score += 20
        reasons.append("اختراق أعلى سعر للشمعة السابقة")
    elif current_price < prev['low']:
        score -= 20
        reasons.append("كسر أدنى سعر للشمعة السابقة")

    display_name = symbol.replace("I:", "")
    
    if score >= 60:
        msg = f"""
🟢 <b>إشارة CALL | {display_name}</b>
<b>السعر:</b> {current_price:.2f}
<b>درجة الثقة:</b> {min(score, 100)}/100

<b>الأسباب:</b>
{chr(10).join(['• ' + r for r in reasons])}

⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)

    elif score <= -50:
        msg = f"""
🔴 <b>إشارة PUT | {display_name}</b>
<b>السعر:</b> {current_price:.2f}
<b>درجة الثقة:</b> {min(abs(score), 100)}/100

<b>الأسباب:</b>
{chr(10).join(['• ' + r for r in reasons])}

⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)

def main():
    global LAST_REPORT_DATE
    
    # 1. تشغيل خادم الويب في الخلفية (لإرضاء Render)
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. تشغيل البوت
    print("🚀 البوت يعمل...")
    send_telegram("✅ <b>تم تشغيل النظام</b>\nمراقبة: SPX, SPY, QQQ")
    
    # إرسال التقرير فور التشغيل
    send_morning_report()
    LAST_REPORT_DATE = datetime.now(NY_TZ).strftime('%Y-%m-%d')
    
    while True:
        now = datetime.now(NY_TZ)
        
        # التقرير الصباحي المجدول (9:00 صباحاً بتوقيت نيويورك)
        if now.weekday() < 5 and now.hour == 9 and now.minute == 0:
            today_str = now.strftime('%Y-%m-%d')
            if LAST_REPORT_DATE != today_str:
                send_morning_report()
                LAST_REPORT_DATE = today_str

        # اصطياد الزخم اللحظي
        if now.weekday() < 5 and (9 <= now.hour < 16): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(2)
        else:
            print(f"⏳ السوق مغلق حالياً ({now.strftime('%H:%M')} NY)")
        
        time.sleep(60)

if __name__ == "__main__":
    main()
