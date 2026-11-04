import logging
import time
import requests
import yfinance as yf
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# متغيرات لمنع تكرار التنبيهات
LAST_ALERT_TIME = {}
ALERT_COOLDOWN = 300  # 5 دقائق بين كل تنبيه لنفس المستوى

def get_spx_data():
    """جلب سعر SPX اللحظي وبيانات آخر ساعة لتحديد المستويات ديناميكياً"""
    try:
        ticker = yf.Ticker("^GSPC")
        # نجلب بيانات آخر يوم بفاصل دقيقة واحدة
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return data
        return None
    except Exception as e:
        logger.error(f"Error fetching price data: {e}")
        return None

def send_telegram_alert(message):
    """إرسال التنبيه إلى تلجرام"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def monitor_market_dynamic():
    """محرك المراقبة الديناميكي (يقرأ الشارت ويحدد المستويات تلقائياً)"""
    logger.info("🚀 Dynamic Live Monitor Started (24/7)...")
    
    while True:
        try:
            df = get_spx_data()
            if df is None or len(df) < 60:
                time.sleep(60)
                continue
            
            current_price = df['Close'].iloc[-1]
            
            # 1. تحديد أعلى قمة وأدنى قاع في آخر ساعة (60 دقيقة) بشكل ديناميكي
            recent_high = df['High'].iloc[-60:].max()
            recent_low = df['Low'].iloc[-60:].min()
            
            # 2. حساب المسافة للاقتراب
            dist_to_res = abs(recent_high - current_price)
            dist_to_sup = abs(current_price - recent_low)
            threshold = current_price * 0.0005  # مسافة 0.05%
            
            now_ts = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")
            
            # 3. فحص الاقتراب من المقاومة (آخر ساعة)
            if dist_to_res <= threshold:
                if now_ts - LAST_ALERT_TIME.get("resistance", 0) > ALERT_COOLDOWN:
                    call_contract = f"SPXW C {int(round(current_price/5)*5 + 5)}"
                    put_contract = f"SPXW P {int(round(current_price/5)*5 - 5)}"
                    
                    msg = f"""
🚨 <b>اقتراب من مقاومة (ديناميكي)</b>
<b>السعر الحالي:</b> {current_price:.2f}
<b>المقاومة (آخر ساعة):</b> {recent_high:.2f}
<b>الوقت:</b> {now_str}

📈 <b>خطة الاختراق (CALL):</b>
• العقد: <code>{call_contract}</code>
• الهدف: {recent_high + 15:.2f}
• الوقف: {recent_high - 8:.2f}

📉 <b>خطة الفشل (PUT):</b>
• العقد: <code>{put_contract}</code>
• الهدف: {recent_high - 15:.2f}
• الوقف: {recent_high + 8:.2f}

⚠️ <i>راقب الحجم عند التنفيذ</i>
"""
                    send_telegram_alert(msg)
                    LAST_ALERT_TIME["resistance"] = now_ts
                    logger.info(f"Alerted Resistance at {recent_high}")

            # 4. فحص الاقتراب من الدعم (آخر ساعة)
            elif dist_to_sup <= threshold:
                if now_ts - LAST_ALERT_TIME.get("support", 0) > ALERT_COOLDOWN:
                    call_contract = f"SPXW C {int(round(current_price/5)*5 + 5)}"
                    put_contract = f"SPXW P {int(round(current_price/5)*5 - 5)}"
                    
                    msg = f"""
🚨 <b>اقتراب من دعم (ديناميكي)</b>
<b>السعر الحالي:</b> {current_price:.2f}
<b>الدعم (آخر ساعة):</b> {recent_low:.2f}
<b>الوقت:</b> {now_str}

📈 <b>خطة الارتداد (CALL):</b>
• العقد: <code>{call_contract}</code>
• الهدف: {recent_low + 15:.2f}
• الوقف: {recent_low - 8:.2f}

📉 <b>خطة الكسر (PUT):</b>
• العقد: <code>{put_contract}</code>
• الهدف: {recent_low - 15:.2f}
• الوقف: {recent_low + 8:.2f}

⚠️ <i>راقب الحجم عند التنفيذ</i>
"""
                    send_telegram_alert(msg)
                    LAST_ALERT_TIME["support"] = now_ts
                    logger.info(f"Alerted Support at {recent_low}")
            
            time.sleep(60) # فحص كل دقيقة
            
        except Exception as e:
            logger.error(f"Dynamic Monitor error: {e}")
            time.sleep(60)
