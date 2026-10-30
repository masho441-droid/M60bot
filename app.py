import os
import time
import requests
from datetime import datetime
import pytz

# ==================== جلب المفاتيح من Render ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
POLYGON_KEY = os.environ.get("POLYGON_KEY")

# ==================== قائمة المراقبة (15 رمزاً) ====================
WATCHLIST = [
    "I:SPX", "I:NDX", # المؤشرات الرئيسية (S&P 500 و Nasdaq 100)
    "SPY", "QQQ", "IWM", "DIA", # الصناديق المتداولة (للمضاربة)
    "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "AMD", "NFLX", "PLTR", "COIN" # الشركات الكبرى
]

# ==================== إعدادات البوت ====================
NY_TZ = pytz.timezone('America/New_York')

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"خطأ في تلقرام: {e}")

def get_stock_data(symbol):
    # تعديل بسيط: المؤشرات في Polygon تحتاج صيغة معينة، لكن v2/aggs تعمل معها
    end_time = int(time.time() * 1000)
    start_time = end_time - (5 * 60 * 1000) 
    
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{start_time}/{end_time}?apiKey={POLYGON_KEY}"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('results'):
            return data['results']
        return None
    except Exception as e:
        print(f"خطأ في جلب {symbol}: {e}")
        return None

def analyze_symbol(symbol):
    bars = get_stock_data(symbol)
    if not bars or len(bars) < 3:
        return

    current_bar = bars[-1]
    current_price = current_bar['c']
    current_volume = current_bar['v']
    
    recent_high = max([b['h'] for b in bars[:-1]])
    recent_low = min([b['l'] for b in bars[:-1]])
    avg_volume = sum([b['v'] for b in bars[:-1]]) / max(len(bars[:-1]), 1)

    # تنظيف اسم الرمز للعرض في تلقرام (إزالة I:)
    display_name = symbol.replace("I:", "")

    if current_price > recent_high and current_volume > (avg_volume * 1.5):
        send_telegram(f"🟢 <b>إشارة CALL</b> | {display_name}\nالسعر: {current_price:.2f} (اختراق صعودي)\nالحجم: {current_volume/avg_volume:.1f}x\n⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')}")
        print(f"CALL Signal: {display_name}")

    elif current_price < recent_low and current_volume > (avg_volume * 1.5):
        send_telegram(f"🔴 <b>إشارة PUT</b> | {display_name}\nالسعر: {current_price:.2f} (كسر هبوطي)\nالحجم: {current_volume/avg_volume:.1f}x\n⏱️ {datetime.now(NY_TZ).strftime('%H:%M:%S')}")
        print(f"PUT Signal: {display_name}")

def main():
    print("🚀 البوت يعمل الآن...")
    send_telegram("✅ <b>تم تشغيل البوت</b>\nيتم الآن مراقبة SPX و NDX والشركات الكبرى.")
    
    while True:
        now = datetime.now(NY_TZ)
        # مراقبة السوق من 9:30 صباحاً إلى 4:00 مساءً (نيويورك)
        if now.weekday() < 5 and (9 <= now.hour < 16): 
            for symbol in WATCHLIST:
                analyze_symbol(symbol)
                time.sleep(0.5) 
        else:
            print(f"⏳ السوق مغلق حالياً ({now.strftime('%H:%M')})")
        
        time.sleep(60)

if __name__ == "__main__":
    main()
