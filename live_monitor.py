import logging
import time
import requests
import os
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

LAST_ALERT_TIME = {}
ALERT_COOLDOWN = 300  # 5 دقائق

# ==================== دالة جلب الأخبار الاقتصادية ====================
def get_economic_news():
    """جلب الأخبار الاقتصادية المهمة (الفيدرالي، التضخم، الوظائف)"""
    try:
        # نستخدم Finnhub API (إذا كان لديك مفتاح) أو نعتمد على بيانات ثابتة
        # هنا نضع تنبيهات يدوية للأحداث الكبرى (يمكنك تعديلها)
        important_events = {
            "FOMC": "اجتماع الفيدرالي (قرار الفائدة)",
            "CPI": "بيان التضخم (مؤشر أسعار المستهلك)",
            "NFP": "بيان الوظائف غير الزراعية"
        }
        # نعيد قائمة الأحداث المهمة لليوم (إذا كان اليوم يصادف حدثاً)
        # في الواقع، يجب جلبها من API، لكن نضعها هنا كدليل
        today_str = datetime.now().strftime("%Y-%m-%d")
        # يمكنك إضافة تواريخ الأحداث هنا يدوياً:
        # events_today = {"2026-11-05": "FOMC", "2026-11-10": "CPI"}
        events_today = {} 
        return events_today.get(today_str, None)
    except Exception as e:
        logger.error(f"News error: {e}")
        return None

# ==================== دالة جلب بيانات SPX ====================
def get_spx_data(interval="1m", period="1d"):
    """جلب بيانات SPX (يدعم فواصل زمنية متعددة)"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    params = {"interval": interval, "range": period}
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            result = data.get("chart", {}).get("result", [])
            if not result: raise Exception("No data")
            chart = result[0]
            timestamps = chart.get("timestamp", [])
            indicators = chart.get("indicators", {}).get("quote", [{}])[0]
            closes = indicators.get("close", [])
            highs = indicators.get("high", [])
            lows = indicators.get("low", [])
            opens = indicators.get("open", [])
            
            valid_data = []
            for i in range(len(timestamps)):
                if all(v is not None for v in [closes[i], highs[i], lows[i], opens[i]]):
                    valid_data.append({"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i]})
            return pd.DataFrame(valid_data)
        except Exception as e:
            logger.warning(f"Yahoo attempt {attempt+1} failed: {e}")
            time.sleep(3)
    return None

# ==================== دالة إرسال التنبيهات ====================
def send_telegram_alert(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

# ==================== المحرك الرئيسي ====================
def monitor_market_dynamic():
    logger.info("🚀 Macro & Micro Monitor Started (24/7)...")
    
    while True:
        try:
            # 1. جلب البيانات اللحظية (للمستويات الصغيرة)
            df_1m = get_spx_data(interval="1m", period="1d")
            # 2. جلب البيانات اليومية (للمستويات الكبيرة والاتجاه)
            df_1d = get_spx_data(interval="1d", period="3mo")
            
            if df_1m is None or df_1d is None or len(df_1m) < 60 or len(df_1d) < 20:
                time.sleep(60)
                continue
            
            current_price = df_1m['close'].iloc[-1]
            now_str = datetime.now().strftime("%H:%M:%S")
            
            # --- حساب الاتجاه اليومي (Bias) ---
            ema20 = df_1d['close'].ewm(span=20).mean().iloc[-1]
            ema50 = df_1d['close'].ewm(span=50).mean().iloc[-1]
            daily_bias = "صاعد 🟢" if current_price > ema20 and ema20 > ema50 else ("هابط 🔴" if current_price < ema20 and ema20 < ema50 else "محايد ⚪")
            
            # --- حساب مستويات السوينغ (اليومية) ---
            daily_high = df_1d['high'].iloc[-2] # قمة الأمس
            daily_low = df_1d['low'].iloc[-2]   # قاع الأمس
            pivot = (daily_high + daily_low + df_1d['close'].iloc[-2]) / 3
            
            # --- حساب مستويات السكالبينغ (آخر ساعة) ---
            recent_high_1h = df_1m['high'].iloc[-60:].max()
            recent_low_1h = df_1m['low'].iloc[-60:].min()
            
            # --- ترشيح العقود ---
            # عقد كول قريب (للسكالبينغ) وعقد كول بعيد (للسوينغ)
            call_scalp = f"SPXW C {int(round(current_price/5)*5 + 5)}"
            call_swing = f"SPXW C {int(round(daily_high/5)*5 + 10)}"
            put_scalp = f"SPXW P {int(round(current_price/5)*5 - 5)}"
            put_swing = f"SPXW P {int(round(daily_low/5)*5 - 10)}"
            
            now_ts = time.time()
            
            # --- فحص الاختراق اليومي (صفقة سوينغ) ---
            if current_price > daily_high and now_ts - LAST_ALERT_TIME.get("swing_high", 0) > ALERT_COOLDOWN:
                news = get_economic_news()
                news_text = f"\n📰 <b>خبر مهم:</b> {news}" if news else ""
                
                msg = f"""
🚀 <b>اختراق قمة الأمس (صفقة سوينغ)</b>
<b>السعر:</b> {current_price:.2f}
<b>قمة الأمس:</b> {daily_high:.2f}
<b>الاتجاه اليومي:</b> {daily_bias}
{news_text}

🎯 <b>العقود المقترحة (CALL):</b>
• قريب (سكالبينغ): <code>{call_scalp}</code>
• بعيد (سوينغ): <code>{call_swing}</code>

📈 <b>الأهداف:</b>
• هدف 1: {daily_high + 20:.2f}
• هدف 2: {daily_high + 40:.2f}
🛑 <b>الوقف:</b> {daily_high - 15:.2f}

⏱️ {now_str}
⚠️ <i>ليست نصيحة مالية</i>
"""
                send_telegram_alert(msg)
                LAST_ALERT_TIME["swing_high"] = now_ts

            # --- فحص كسر الدعم اليومي (صفقة سوينغ) ---
            elif current_price < daily_low and now_ts - LAST_ALERT_TIME.get("swing_low", 0) > ALERT_COOLDOWN:
                news = get_economic_news()
                news_text = f"\n📰 <b>خبر مهم:</b> {news}" if news else ""
                
                msg = f"""
🔻 <b>كسر قاع الأمس (صفقة سوينغ)</b>
<b>السعر:</b> {current_price:.2f}
<b>قاع الأمس:</b> {daily_low:.2f}
<b>الاتجاه اليومي:</b> {daily_bias}
{news_text}

🎯 <b>العقود المقترحة (PUT):</b>
• قريب (سكالبينغ): <code>{put_scalp}</code>
• بعيد (سوينغ): <code>{put_swing}</code>

📉 <b>الأهداف:</b>
• هدف 1: {daily_low - 20:.2f}
• هدف 2: {daily_low - 40:.2f}
🛑 <b>الوقف:</b> {daily_low + 15:.2f}

⏱️ {now_str}
⚠️ <i>ليست نصيحة مالية</i>
"""
                send_telegram_alert(msg)
                LAST_ALERT_TIME["swing_low"] = now_ts

            # --- فحص المستويات اللحظية (سكالبينغ) ---
            dist_to_res = abs(recent_high_1h - current_price)
            dist_to_sup = abs(current_price - recent_low_1h)
            threshold = current_price * 0.0005
            
            if dist_to_res <= threshold and now_ts - LAST_ALERT_TIME.get("resistance", 0) > ALERT_COOLDOWN:
                msg = f"""
⚠️ <b>اقتراب من مقاومة (آخر ساعة)</b>
<b>السعر:</b> {current_price:.2f} | <b>المقاومة:</b> {recent_high_1h:.2f}
<b>الاتجاه اليومي:</b> {daily_bias}

📈 <b>خطة الاختراق (CALL):</b> <code>{call_scalp}</code>
📉 <b>خطة الفشل (PUT):</b> <code>{put_scalp}</code>
⏱️ {now_str}
"""
                send_telegram_alert(msg)
                LAST_ALERT_TIME["resistance"] = now_ts
                
            elif dist_to_sup <= threshold and now_ts - LAST_ALERT_TIME.get("support", 0) > ALERT_COOLDOWN:
                msg = f"""
⚠️ <b>اقتراب من دعم (آخر ساعة)</b>
<b>السعر:</b> {current_price:.2f} | <b>الدعم:</b> {recent_low_1h:.2f}
<b>الاتجاه اليومي:</b> {daily_bias}

📈 <b>خطة الارتداد (CALL):</b> <code>{call_scalp}</code>
📉 <b>خطة الكسر (PUT):</b> <code>{put_scalp}</code>
⏱️ {now_str}
"""
                send_telegram_alert(msg)
                LAST_ALERT_TIME["support"] = now_ts

            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(60)
