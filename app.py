import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# ==================== جلب المفاتيح من Render ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLYGON_KEY = os.environ.get("POLYGON_KEY")

# ==================== قائمة المراقبة (15 رمزاً) ====================
# المؤشرات الرئيسية، الصناديق المتداولة، وأقوى أسهم العقود
WATCHLIST = [
    "I:SPX", "I:NDX", "SPY", "QQQ", "IWM", # المؤشرات والصناديق
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "AMD", "NFLX", "PLTR" # الأسهم
]

NY_TZ = pytz.timezone('America/New_York')

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"خطأ تلقرام: {e}")

def get_polygon_data(symbol, timespan="minute", multiplier=1, limit=50):
    """جلب البيانات من Polygon.io"""
    end_time = int(time.time() * 1000)
    # نجلب بيانات آخر ساعتين لتكون كافية لحساب المؤشرات
    start_time = end_time - (120 * 60 * 1000) 
    
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start_time}/{end_time}?apiKey={POLYGON_KEY}&limit={limit}"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('results'):
            df = pd.DataFrame(data['results'])
            df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 't': 'time'}, inplace=True)
            return df
        return None
    except Exception as e:
        print(f"خطأ في جلب {symbol}: {e}")
        return None

def calculate_indicators(df):
    """حساب المؤشرات الفنية الأساسية"""
    if df is None or len(df) < 20:
        return None
    
    # EMA
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Volume Average
    df['Vol_Avg'] = df['volume'].rolling(window=20).mean()
    
    return df

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
    
    # تجهيز أسباب الإشارة والنقاط
    reasons = []
    score = 0

    # 1. طبقة الاتجاه (Trend)
    if last['EMA9'] > last['EMA21'] and prev['EMA9'] <= prev['EMA21']:
        score += 30
        reasons.append("تقاطع EMA9 فوق EMA21 (صعود)")
    elif last['EMA9'] < last['EMA21']:
        score -= 20
        reasons.append("EMA9 تحت EMA21 (هبوط)")

    # 2. طبقة الزخم (Momentum)
    if 40 < last['RSI'] < 70:
        score += 15
        reasons.append(f"RSI صحي ({last['RSI']:.1f})")
    elif last['RSI'] >= 70:
        score += 10
        reasons.append(f"RSI في ذروة الشراء ({last['RSI']:.1f})")
    elif last['RSI'] < 30:
        score -= 10
        reasons.append(f"RSI في ذروة البيع ({last['RSI']:.1f})")

    # 3. طبقة الحجم (Volume)
    if current_volume > (avg_volume * 1.5):
        score += 25
        reasons.append(f"انفجار في الحجم ({current_volume/avg_volume:.1f}x)")

    # 4. طبقة السعر (Price Action)
    if current_price > prev['high']:
        score += 20
        reasons.append("اختراق أعلى سعر للشمعة السابقة")
    elif current_price < prev['low']:
        score -= 20
        reasons.append("كسر أدنى سعر للشعبة السابقة")

    # ==================== قرار الإشارة ====================
    display_name = symbol.replace("I:", "")
    
    # إشارة CALL (شراء)
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
        print(f"✅ CALL: {display_name} (Score: {score})")

    # إشارة PUT (بيع)
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
        print(f"✅ PUT: {display_name} (Score: {score})")

def main():
    print("🚀 البوت المطور يعمل الآن...")
    send_telegram("✅ <b>تم تشغيل نظام اصطياد العقود</b>\nالبوت الآن يراقب SPX, NDX وأقوى 13 سهماً للعقود.")
    
    while True:
        now = datetime.now(NY_TZ)
        # نعمل فقط أثناء ساعات السوق (9:30 صباحاً - 4:00 مساءً)
        if now.weekday() < 5 and (9 <= now.hour < 16): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(2) # تأخير لتجنب حظر Polygon
        else:
            print(f"⏳ السوق مغلق حالياً ({now.strftime('%H:%M')} NY)")
        
        # انتظار دقيقة واحدة قبل الفحص التالي
        time.sleep(60)

if __name__ == "__main__":
    main()
