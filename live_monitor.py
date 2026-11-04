import logging, time, requests, os
from datetime import datetime, time as dtime
import pandas as pd

logger = logging.getLogger(__name__)

# حالة الصفقة - البوت يتذكرها
ACTIVE_TRADE = None
LAST_ALERT = 0
COOLDOWN = 60

def get_spx_1m():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, params={"range": "1d", "interval": "1m"}, timeout=10)
        data = r.json()
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({"time": pd.to_datetime(ts, unit="s"), "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]})
        return df.dropna()
    except Exception as e:
        logger.error(f"Data error: {e}")
        return None

def send_alert(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def monitor_market_dynamic():
    global ACTIVE_TRADE, LAST_ALERT
    logger.info("VWAP + ORB Monitor Started - With Trade Tracking")
    send_alert("✅ <b>البوت اشتغل - استراتيجية VWAP + افتتاح 15 دقيقة</b>\nيراقب السوق ويمسك الصفقة لين إغلاقها")

    while True:
        try:
            df = get_spx_1m()
            if df is None or len(df) < 30:
                time.sleep(60)
                continue

            price = float(df['close'].iloc[-1])
            now_et = datetime.now() # عدّلها لتوقيت نيويورك في السيرفر
            now_str = now_et.strftime("%H:%M:%S")

            # --- حساب VWAP ---
            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
            vwap = float(df['vwap'].iloc[-1])

            # --- افتتاح أول 15 دقيقة (أول 15 شمعة 1د) ---
            orb = df.head(15)
            orb_high = float(orb['high'].max())
            orb_low = float(orb['low'].min())

            # ========== 1. إذا ما عندنا صفقة، ندور دخول ==========
            if ACTIVE_TRADE is None:
                # لازم نكون بعد أول 15 دقيقة
                if len(df) < 16:
                    time.sleep(60)
                    continue

                # نمنع الدخول بعد 11:30 نيويورك - نستخدم عدد الشمعات تقريباً
                # السوق يفتح 9:30، يعني شمعة 120 = 11:30
                if len(df) > 120:
                    time.sleep(60)
                    continue

                # --- شرط CALL ---
                # السعر فوق VWAP + فوق قمة الافتتاح + رجع يختبرها
                # نستخدم تبسيط: السعر فوق الاثنين و قريب من قمة الافتتاح (ريتست)
                is_call_setup = price > vwap and price > orb_high and abs(price - orb_high) <= 3.0
                # --- شرط PUT ---
                is_put_setup = price < vwap and price < orb_low and abs(price - orb_low) <= 3.0

                if is_call_setup and time.time() - LAST_ALERT > COOLDOWN:
                    base = round(price / 5) * 5
                    contract = f"SPXW C {base + 5}"
                    ACTIVE_TRADE = {
                        "type": "CALL", "contract": contract,
                        "entry": price, "tp1": price + 15, "tp2": price + 25,
                        "sl": price - 8, "tp1_hit": False
                    }
                    LAST_ALERT = time.time()
                    send_alert(f"""
🚨 <b>دخول CALL - VWAP + كسر افتتاح</b>
<b>السعر:</b> {price:.2f}
<b>VWAP:</b> {vwap:.2f} | <b>قمة الافتتاح:</b> {orb_high:.2f}
<b>العقد:</b> <code>{contract}</code>

🎯 <b>هدف 1:</b> {price + 15:.2f} - بيع نص الكمية
🎯 <b>هدف 2:</b> {price + 25:.2f} - بيع الباقي
🛑 <b>وقف:</b> {price - 8:.2f}

⏱️ {now_str}
<i>البوت الحين يراقب الصفقة معك، لا تدخل صفقة ثانية</i>
""")

                elif is_put_setup and time.time() - LAST_ALERT > COOLDOWN:
                    base = round(price / 5) * 5
                    contract = f"SPXW P {base - 5}"
                    ACTIVE_TRADE = {
                        "type": "PUT", "contract": contract,
                        "entry": price, "tp1": price - 15, "tp2": price - 25,
                        "sl": price + 8, "tp1_hit": False
                    }
                    LAST_ALERT = time.time()
                    send_alert(f"""
🚨 <b>دخول PUT - VWAP + كسر افتتاح</b>
<b>السعر:</b> {price:.2f}
<b>VWAP:</b> {vwap:.2f} | <b>قاع الافتتاح:</b> {orb_low:.2f}
<b>العقد:</b> <code>{contract}</code>

🎯 <b>هدف 1:</b> {price - 15:.2f} - بيع نص الكمية
🎯 <b>هدف 2:</b> {price - 25:.2f} - بيع الباقي
🛑 <b>وقف:</b> {price + 8:.2f}

⏱️ {now_str}
<i>البوت الحين يراقب الصفقة معك، لا تدخل صفقة ثانية</i>
""")

            # ========== 2. إذا عندنا صفقة، نتابعها لين تقفل ==========
            else:
                t = ACTIVE_TRADE
                # --- CALL ---
                if t["type"] == "CALL":
                    if price >= t["tp2"]:
                        send_alert(f"✅ <b>الهدف الثاني تحقق - أغلق الصفقة</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | الآن: {price:.2f} | ربح: +{price - t['entry']:.2f} نقطة\n⏱️ {now_str}")
                        ACTIVE_TRADE = None
                    elif price >= t["tp1"] and not t["tp1_hit"]:
                        t["tp1_hit"] = True
                        # نحرك الوقف للدخول بعد الهدف الأول - حماية
                        t["sl"] = t["entry"]
                        send_alert(f"🎯 <b>الهدف الأول تحقق!</b>\nالعقد: <code>{t['contract']}</code>\nبيع نص الكمية، الوقف صار على الدخول: {t['entry']:.2f}\nالسعر الآن: {price:.2f}\n⏱️ {now_str}\n<i>أنا أتابع الباقي</i>")
                    elif price <= t["sl"]:
                        reason = "ضرب الوقف" if not t["tp1_hit"] else "ضرب وقف الحماية على الدخول"
                        send_alert(f"🛑 <b>{reason} - أغلق الصفقة</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f}\n⏱️ {now_str}\n<i>لا تعوض اليوم، انتهت الصفقة</i>")
                        ACTIVE_TRADE = None

                # --- PUT ---
                else:
                    if price <= t["tp2"]:
                        send_alert(f"✅ <b>الهدف الثاني تحقق - أغلق الصفقة</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | الآن: {price:.2f} | ربح: +{t['entry'] - price:.2f} نقطة\n⏱️ {now_str}")
                        ACTIVE_TRADE = None
                    elif price <= t["tp1"] and not t["tp1_hit"]:
                        t["tp1_hit"] = True
                        t["sl"] = t["entry"]
                        send_alert(f"🎯 <b>الهدف الأول تحقق!</b>\nالعقد: <code>{t['contract']}</code>\nبيع نص الكمية، الوقف صار على الدخول: {t['entry']:.2f}\nالسعر الآن: {price:.2f}\n⏱️ {now_str}\n<i>أنا أتابع الباقي</i>")
                    elif price >= t["sl"]:
                        reason = "ضرب الوقف" if not t["tp1_hit"] else "ضرب وقف الحماية على الدخول"
                        send_alert(f"🛑 <b>{reason} - أغلق الصفقة</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f}\n⏱️ {now_str}\n<i>لا تعوض اليوم، انتهت الصفقة</i>")
                        ACTIVE_TRADE = None

            time.sleep(60)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(60)
