import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from flask import Flask
import threading

# ==================== الإعدادات ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLYGON_KEY = os.environ.get("POLYGON_KEY")

WATCHLIST = ["SPY", "QQQ"]
NY_TZ = pytz.timezone('America/New_York')
LAST_REPORT_DATE = None 

# خادم ويب وهمي لإرضاء Render
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

def get_polygon_data(symbol):
    """جلب بيانات 5 دقائق (لرؤية الصورة الأوضح ومنع الضوضاء)"""
    end_time = int(time.time() * 1000)
    start_time = end_time - (240 * 60 * 1000) # آخر 4 ساعات
    # نستخدم 5 دقائق بدلاً من 1 لتقليل الإشارات الكاذبة
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

def get_last_closed_daily_data(symbol):
    """جلب بيانات الأمس للتقرير الصباحي"""
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
    
    # 1. المؤشرات الأساسية
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # 2. حساب VWAP التقريبي (متوسط السعر المرجح بالحجم)
    df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
    df['VWAP'] = (df['Typical_Price'] * df['volume']).cumsum() / df['volume'].cumsum()
    
    # 3. حساب ATR (لأهداف دقيقة)
    df['TR'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), 
                          abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    
    # 4. RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 5. متوسط الحجم
    df['Vol_Avg'] = df['volume'].rolling(window=10).mean()
    
    return df

# ==================== التقرير الصباحي ====================
def send_morning_report():
    df = get_last_closed_daily_data("SPY")
    if df is None or len(df) < 2:
        send_telegram("⚠️ <b>فشل جلب بيانات التقرير.</b>")
        return

    prev_day = df.iloc[-1]
    prev_close = prev_day['close'] * 10
    high = prev_day['high'] * 10
    low = prev_day['low'] * 10
    
    pivot = (high + low + prev_close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)

    trend = "صاعد 🟢" if prev_close > (df.iloc[-2]['close'] * 10) else "هابط 🔴"
    
    msg = f"""
🌅 <b>التقرير الصباحي | S&P 500 (SPX)</b>
<i>(مستخرج من بيانات SPY)</i>

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

⚠️ <i>ليست نصيحة مالية.</i>
⏱️ {datetime.now(NY_TZ).strftime('%Y-%m-%d')}
"""
    send_telegram(msg)
    print("✅ تم إرسال التقرير الصباحي")

# ==================== محرك الإشارات الاحترافي ====================
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
    
    # قمة وقاع آخر 15 دقيقة (3 شموع من فئة 5 دقائق)
    recent_high = df['high'].iloc[-4:-1].max()
    recent_low = df['low'].iloc[-4:-1].min()
    
    reasons = []
    score = 0

    # 1. فلتر الاتجاه (EMA & VWAP)
    # الإشارة لا تؤخذ إلا إذا كان السعر في الاتجاه الصحيح مقارنة بـ VWAP
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

    # 2. فلتر الزخم (RSI) - نمنع الدخول في التشبع
    if 45 < last['RSI'] < 75 and score > 0:
        score += 15
        reasons.append(f"RSI إيجابي ({last['RSI']:.1f})")
    elif 25 < last['RSI'] < 55 and score < 0:
        score -= 15
        reasons.append(f"RSI سلبي ({last['RSI']:.1f})")
    elif last['RSI'] >= 80:
        score -= 30 # عقاب: لا تشتري في القمة
        reasons.append("تحذير: RSI في ذروة الشراء!")
    elif last['RSI'] <= 20:
        score += 30 # عقاب: لا تبيع في القاع
        reasons.append("تحذير: RSI في ذروة البيع!")

    # 3. فلتر السيولة (Volume)
    if current_volume > (avg_volume * 1.5):
        score += 20 if score > 0 else -20
        reasons.append(f"انفجار في الحجم ({current_volume/avg_volume:.1f}x)")

    # 4. فلتر الاختراق (Breakout)
    if current_price > recent_high and score > 0:
        score += 30
        reasons.append("اختراق قمة الـ 15 دقيقة")
    elif current_price < recent_low and score < 0:
        score -= 30
        reasons.append("كسر قاع الـ 15 دقيقة")

    display_name = symbol.replace("I:", "")
    
    # ==================== إشارة CALL ====================
    if score >= 70: # رفعنا العتبة لضمان الدقة
        target1 = current_price + (atr * 1.5)
        target2 = current_price + (atr * 3.0)
        stop_loss = current_price - (atr * 1.0)
        
        msg = f"""
🟢 <b>إشارة CALL عالية الدقة | {display_name}</b>
<b>السعر:</b> {current_price:.2f}
<b>درجة الثقة:</b> {min(score, 100)}/100

🎯 <b>الأهداف:</b>
• الهدف 1 (قريب): {target1:.2f}
• الهدف 2 (بعيد): {target2:.2f}
🛑 <b>وقف الخسارة:</b> {stop_loss:.2f}

<b>الأسباب الاحترافية:</b>
{chr(10).join(['• ' + r for r in reasons])}

⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)
        print(f"✅ CALL: {display_name}")

    # ==================== إشارة PUT ====================
    elif score <= -70:
        target1 = current_price - (atr * 1.5)
        target2 = current_price - (atr * 3.0)
        stop_loss = current_price + (atr * 1.0)
        
        msg = f"""
🔴 <b>إشارة PUT عالية الدقة | {display_name}</b>
<b>السعر:</b> {current_price:.2f}
<b>درجة الثقة:</b> {min(abs(score), 100)}/100

🎯 <b>الأهداف:</b>
• الهدف 1 (قريب): {target1:.2f}
• الهدف 2 (بعيد): {target2:.2f}
🛑 <b>وقف الخسارة:</b> {stop_loss:.2f}

<b>الأسباب الاحترافية:</b>
{chr(10).join(['• ' + r for r in reasons])}

⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')} (NY)
⚠️ <i>ليست نصيحة مالية</i>
"""
        send_telegram(msg)
        print(f"✅ PUT: {display_name}")

# ==================== التشغيل الرئيسي ====================
def main():
    global LAST_REPORT_DATE
    
    threading.Thread(target=run_web_server, daemon=True).start()
    
    print("🚀 محرك القناص الاحترافي يعمل...")
    send_telegram("✅ <b>تم تشغيل محرك القناص الاحترافي</b>\nالمراقبة: SPY, QQQ\nيعتمد على: VWAP + الاختراق + الحجم + الأهداف الذكية.")
    
    send_morning_report()
    LAST_REPORT_DATE = datetime.now(NY_TZ).strftime('%Y-%m-%d')
    
    while True:
        now = datetime.now(NY_TZ)
        
        # التقرير الصباحي
        if now.weekday() < 5 and now.hour == 9 and now.minute == 0:
            today_str = now.strftime('%Y-%m-%d')
            if LAST_REPORT_DATE != today_str:
                send_morning_report()
                LAST_REPORT_DATE = today_str

        # فحص السوق (فقط من 10:00 صباحاً لتجنب أول 30 دقيقة من العشوائية)
        if now.weekday() < 5 and (10 <= now.hour < 16): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(2)
        else:
            print(f"⏳ السوق مغلق أو في فترة العشوائية ({now.strftime('%H:%M')} NY)")
        
        time.sleep(60)

if __name__ == "__main__":
    main()
