import logging, time, requests, os
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

ACTIVE_TRADE = None
LAST_ALERT = 0
TRADES_TODAY = 0
LOSSES_IN_ROW = 0
LAST_TRADE_CLOSE_TIME = 0

def get_spx_1m():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, params={"range": "1d", "interval": "1m"}, timeout=10)
        data = r.json()
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({
            "time": pd.to_datetime(ts, unit="s"),
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"]
        })
        return df.dropna()
    except Exception as e:
        logger.error(f"Data error: {e}")
        return None

def send_alert(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def monitor_market_dynamic():
    global ACTIVE_TRADE, LAST_ALERT, TRADES_TODAY, LOSSES_IN_ROW, LAST_TRADE_CLOSE_TIME
    logger.info("VWAP + ORB + EMA9 + Volume - All Day - 30min Timeout")
    send_alert("✅ <b>البوت اشتغل - طول اليوم - خروج بعد 30 دقيقة</b>\nVWAP + افتتاح + EMA9 + فوليوم\nعقد واحد | 10 صفقات | ما تعلق الصفقة أكثر من 30 د")

    while True:
        try:
            df = get_spx_1m()
            if df is None or len(df) < 30:
                time.sleep(60)
                continue

            price = float(df['close'].iloc[-1])
            now_str = datetime.now().strftime("%H:%M:%S")

            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
            vwap = float(df['vwap'].iloc[-1])

            df['ema9'] = df['close'].ewm(span=9).mean()
            ema9 = float(df['ema9'].iloc[-1])

            avg_vol_raw = df['volume'].tail(20).mean()
            avg_vol = float(avg_vol_raw)
            last_vol_raw = df['volume'].iloc[-1]
            last_vol = float(last_vol_raw)
            vol_ok = last_vol > avg_vol * 1.2

            orb = df.head(15)
            orb_high_raw = orb['high'].max()
            orb_high = float(orb_high_raw)
            orb_low_raw = orb['low'].min()
            orb_low = float(orb_low_raw)

            if ACTIVE_TRADE is None:
                if TRADES_TODAY >= 10:
                    time.sleep(60)
                    continue
                if LOSSES_IN_ROW >= 3:
                    time.sleep(60)
                    continue
                if time.time() - LAST_TRADE_CLOSE_TIME < 300 and TRADES_TODAY > 0:
                    time.sleep(60)
                    continue
                if len(df) < 16:
                    time.sleep(60)
                    continue
                if len(df) > 360:
                    time.sleep(60)
                    continue

                is_call = price > vwap and price > orb_high and price > ema9 and vol_ok
                is_put = price < vwap and price < orb_low and price < ema9 and vol_ok

                if is_call and time.time() - LAST_ALERT > 60:
                    base = round(price / 5) * 5
                    contract = f"SPXW C {base + 5}"
                    ACTIVE_TRADE = {"type": "CALL", "contract": contract, "entry": price, "tp1": price + 15, "tp2": price + 25, "sl": price - 8, "tp1_hit": False, "entry_time": time.time()}
                    LAST_ALERT = time.time()
                    send_alert(f"🚨 <b>دخول CALL - عقد واحد - صفقة {TRADES_TODAY + 1}/10</b>\n<b>السعر:</b> {price:.2f}\n<b>VWAP:</b> {vwap:.2f} | <b>EMA9:</b> {ema9:.2f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {price + 15:.2f}\n🛑 وقف: {price - 8:.2f}\n⏱️ {now_str}\n<i>بقفلها بعد 30 دقيقة إذا ما تحركت</i>")
                elif is_put and time.time() - LAST_ALERT > 60:
                    base = round(price / 5) * 5
                    contract = f"SPXW P {base - 5}"
                    ACTIVE_TRADE = {"type": "PUT", "contract": contract, "entry": price, "tp1": price - 15, "tp2": price - 25, "sl": price + 8, "tp1_hit": False, "entry_time": time.time()}
                    LAST_ALERT = time.time()
                    send_alert(f"🚨 <b>دخول PUT - عقد واحد - صفقة {TRADES_TODAY + 1}/10</b>\n<b>السعر:</b> {price:.2f}\n<b>VWAP:</b> {vwap:.2f} | <b>EMA9:</b> {ema9:.2f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {price - 15:.2f}\n🛑 وقف: {price + 8:.2f}\n⏱️ {now_str}\n<i>بقفلها بعد 30 دقيقة إذا ما تحركت</i>")

            else:
                t = ACTIVE_TRADE

                # خروج بعد 30 دقيقة - عشان ما تعلق الصفقة وتمنع باقي الصفقات
                if time.time() - t.get("entry_time", time.time()) > 1800:
                    if t["type"] == "CALL":
                        profit = price - t["entry"]
                    else:
                        profit = t["entry"] - price
                    is_win = profit > 0
                    TRADES_TODAY += 1
                    if is_win:
                        LOSSES_IN_ROW = 0
                    else:
                        LOSSES_IN_ROW += 1
                    LAST_TRADE_CLOSE_TIME = time.time()
                    send_alert(f"⏰ <b>قفل - انتهى الوقت 30 دقيقة</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f} | النتيجة: {profit:+.2f} نقطة\nالصفقة: {TRADES_TODAY}/10\n⏱️ {now_str}\n<i>بدور لك صفقة جديدة بعد 5 دقايق</i>")
                    ACTIVE_TRADE = None
                    time.sleep(60)
                    continue

                if t["type"] == "CALL":
                    if price >= t["tp1"] and not t["tp1_hit"]:
                        t["tp1_hit"] = True
                        t["sl"] = t["entry"]
                        send_alert(f"🎯 <b>هدف 1 تحقق {t['tp1']:.2f} - خلك لا تبيع</b>\nالعقد: <code>{t['contract']}</code>\nحركت الوقف على الدخول: {t['entry']:.2f}\n⏱️ {now_str}")
                    elif price >= t["tp2"]:
                        old = t["tp2"]
                        t["sl"] = old - 5
                        t["tp1"] = old
                        t["tp2"] = old + 15
                        send_alert(f"✅ <b>هدف تحقق {old:.2f} - خلك، جددت الهدف</b>\nالوقف المتحرك: {t['sl']:.2f}\n🎯 الهدف الجديد: {t['tp2']:.2f}\n⏱️ {now_str}")
                    elif price <= t["sl"]:
                        profit = price - t["entry"]
                        is_win = profit > 0
                        TRADES_TODAY += 1
                        if is_win:
                            LOSSES_IN_ROW = 0
                        else:
                            LOSSES_IN_ROW += 1
                        LAST_TRADE_CLOSE_TIME = time.time()
                        send_alert(f"🛑 <b>قفل الحين كامل</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f} | النتيجة: {profit:+.2f} نقطة\n⏱️ {now_str}")
                        ACTIVE_TRADE = None
                else:
                    if price <= t["tp1"] and not t["tp1_hit"]:
                        t["tp1_hit"] = True
                        t["sl"] = t["entry"]
                        send_alert(f"🎯 <b>هدف 1 تحقق {t['tp1']:.2f} - خلك لا تبيع</b>\nالعقد: <code>{t['contract']}</code>\nحركت الوقف على الدخول: {t['entry']:.2f}\n⏱️ {now_str}")
                    elif price <= t["tp2"]:
                        old = t["tp2"]
                        t["sl"] = old + 5
                        t["tp1"] = old
                        t["tp2"] = old - 15
                        send_alert(f"✅ <b>هدف تحقق {old:.2f} - خلك، جددت الهدف</b>\nالوقف المتحرك: {t['sl']:.2f}\n🎯 الهدف الجديد: {t['tp2']:.2f}\n⏱️ {now_str}")
                    elif price >= t["sl"]:
                        profit = t["entry"] - price
                        is_win = profit > 0
                        TRADES_TODAY += 1
                        if is_win:
                            LOSSES_IN_ROW = 0
                        else:
                            LOSSES_IN_ROW += 1
                        LAST_TRADE_CLOSE_TIME = time.time()
                        send_alert(f"🛑 <b>قفل الحين كامل</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f} | النتيجة: {profit:+.2f} نقطة\n⏱️ {now_str}")
                        ACTIVE_TRADE = None

            time.sleep(60)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(60)
