import logging, time, requests, os
from datetime import datetime, timezone
import pandas as pd

logger = logging.getLogger(__name__)
ACTIVE_TRADE = None
LAST_ALERT = 0
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
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def get_swing_levels(df):
    highs, lows = [], []
    for i in range(5, len(df) - 5):
        h = float(df['high'].iloc[i])
        l = float(df['low'].iloc[i])
        if h == float(df['high'].iloc[i-5:i+6].max()) and h > float(df['high'].iloc[i-1]) and h > float(df['high'].iloc[i+1]):
            highs.append((i, h))
        if l == float(df['low'].iloc[i-5:i+6].min()) and l < float(df['low'].iloc[i-1]) and l < float(df['low'].iloc[i+1]):
            lows.append((i, l))
    return highs, lows

def monitor_market_dynamic():
    global ACTIVE_TRADE, LAST_ALERT, LAST_TRADE_CLOSE_TIME
    logger.info("SPX - Chart Structure Only - Final")
    send_alert("✅ <b>البوت اشتغل - شارت فقط - نهائي</b>\nاختراق قمة / كسر قاع حي | VWAP | EMA 9/21/50")

    while True:
        try:
            df = get_spx_1m()
            if df is None or len(df) < 80:
                time.sleep(60)
                continue

            price = float(df['close'].iloc[-1])
            prev_price = float(df['close'].iloc[-2])
            now_str = datetime.now().strftime("%H:%M:%S")

            utc_now = datetime.now(timezone.utc)
            month = utc_now.month
            ny_offset = -5 if month in [11, 12, 1, 2, 3] else -4
            ny_hour = (utc_now.hour + ny_offset) % 24
            ny_time = ny_hour * 60 + utc_now.minute
            is_hero_time = ny_time >= 840

            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
            vwap = float(df['vwap'].iloc[-1])
            prev_vwap = float(df['vwap'].iloc[-2])

            df['ema9'] = df['close'].ewm(span=9).mean()
            df['ema21'] = df['close'].ewm(span=21).mean()
            df['ema50'] = df['close'].ewm(span=50).mean()
            ema9 = float(df['ema9'].iloc[-1])
            ema21 = float(df['ema21'].iloc[-1])
            ema50 = float(df['ema50'].iloc[-1])

            avg_vol = float(df['volume'].tail(20).mean())
            last_vol = float(df['volume'].iloc[-1])
            vol_ok = last_vol > avg_vol * 1.3
            vol_hero = last_vol > avg_vol * 1.8

            swing_highs, swing_lows = get_swing_levels(df)
            last_swing_high = swing_highs[-1][1] if swing_highs else None
            last_swing_low = swing_lows[-1][1] if swing_lows else None

            last_move = 20
            if len(swing_highs) >= 1 and len(swing_lows) >= 1:
                if swing_highs[-1][0] > swing_lows[-1][0]:
                    last_move = abs(swing_highs[-1][1] - swing_lows[-1][1])
                else:
                    last_move = abs(swing_lows[-1][1] - swing_highs[-1][1])
                last_move = min(max(last_move, 8), 40)

            is_chop = abs(ema9 - ema21) < 2.0
            last20 = df.iloc[-21:-1]
            range20 = float(last20['high'].max() - last20['low'].min())
            is_coiled = range20 < 15
            near_vwap = abs(price - vwap) < 10

            if ACTIVE_TRADE is None:
                if time.time() - LAST_TRADE_CLOSE_TIME < 300 and LAST_TRADE_CLOSE_TIME > 0:
                    time.sleep(60)
                    continue
                if last_swing_high is None or last_swing_low is None:
                    time.sleep(60)
                    continue

                if is_hero_time:
                    hero_high = float(last20['high'].max())
                    hero_low = float(last20['low'].min())
                    compress_height = hero_high - hero_low
                    hero_call = is_coiled and near_vwap and price > hero_high and vol_hero and ema9 > ema21
                    hero_put = is_coiled and near_vwap and price < hero_low and vol_hero and ema9 < ema21
                    if hero_call and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW C {base + 25}"
                        tp1 = hero_high + compress_height
                        tp2 = tp1 + compress_height
                        for _, h in swing_highs:
                            if h > tp1:
                                tp2 = h
                                break
                        ACTIVE_TRADE = {"type": "CALL", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": hero_low, "tp1_hit": False, "entry_time": time.time(), "is_hero": True, "last_move": compress_height}
                        LAST_ALERT = time.time()
                        send_alert(f"🔥 <b>دخول HERO CALL - اختراق انضغاط</b>\n<b>السعر:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر انضغاط: {hero_high:.2f} | طول الانضغاط: {compress_height:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f} (هدف النموذج)\n🎯 هدف 2: {tp2:.2f} (قمة شارت)\n🛑 وقف: {hero_low:.2f} (رجوع داخل الانضغاط = فشل)\n⏱️ {now_str}")
                    elif hero_put and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW P {base - 25}"
                        tp1 = hero_low - compress_height
                        tp2 = tp1 - compress_height
                        for _, l in reversed(swing_lows):
                            if l < tp1:
                                tp2 = l
                                break
                        ACTIVE_TRADE = {"type": "PUT", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": hero_high, "tp1_hit": False, "entry_time": time.time(), "is_hero": True, "last_move": compress_height}
                        LAST_ALERT = time.time()
                        send_alert(f"🔥 <b>دخول HERO PUT - كسر انضغاط</b>\n<b>السعر:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر انضغاط: {hero_low:.2f} | طول الانضغاط: {compress_height:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f} (هدف النموذج)\n🎯 هدف 2: {tp2:.2f} (قاع شارت)\n🛑 وقف: {hero_high:.2f} (رجوع داخل الانضغاط = فشل)\n⏱️ {now_str}")
                else:
                    if is_chop:
                        time.sleep(60)
                        continue
                    up_trend = ema9 > ema21 and ema21 > ema50
                    down_trend = ema9 < ema21 and ema21 < ema50
                    call_break = price > last_swing_high and prev_price <= last_swing_high + 1 and price > vwap
                    put_break = price < last_swing_low and prev_price >= last_swing_low - 1 and price < vwap
                    vwap_up = vwap > prev_vwap
                    vwap_down = vwap < prev_vwap
                    is_call = up_trend and call_break and vwap_up and vol_ok
                    is_put = down_trend and put_break and vwap_down and vol_ok
                    if is_call and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW C {base + 5}"
                        candidates = [h for _, h in swing_highs if h > price + 2]
                        tp1 = min(candidates) if candidates else last_swing_high + last_move
                        tp2 = last_swing_high + last_move
                        if tp2 <= tp1:
                            tp2 = tp1 + last_move
                        sl = min(float(df['low'].iloc[-1]), last_swing_high - 2)
                        ACTIVE_TRADE = {"type": "CALL", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": sl, "tp1_hit": False, "entry_time": time.time(), "is_hero": False, "last_move": last_move}
                        LAST_ALERT = time.time()
                        send_alert(f"🚨 <b>دخول CALL - اختراق قمة شارت</b>\n<b>السعر:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر قمة: {last_swing_high:.2f} | طول الحركة: {last_move:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f} (قمة شارت)\n🎯 هدف 2: {tp2:.2f} (هدف النموذج)\n🛑 وقف: {sl:.2f} (رجوع تحت الكسر = فشل)\n⏱️ {now_str}")
                    elif is_put and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW P {base - 5}"
                        candidates = [l for _, l in swing_lows if l < price - 2]
                        tp1 = max(candidates) if candidates else last_swing_low - last_move
                        tp2 = last_swing_low - last_move
                        if tp2 >= tp1:
                            tp2 = tp1 - last_move
                        sl = max(float(df['high'].iloc[-1]), last_swing_low + 2)
                        ACTIVE_TRADE = {"type": "PUT", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": sl, "tp1_hit": False, "entry_time": time.time(), "is_hero": False, "last_move": last_move}
                        LAST_ALERT = time.time()
                        send_alert(f"🚨 <b>دخول PUT - كسر قاع شارت</b>\n<b>السعر:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر قاع: {last_swing_low:.2f} | طول الحركة: {last_move:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f} (قاع شارت)\n🎯 هدف 2: {tp2:.2f} (هدف النموذج)\n🛑 وقف: {sl:.2f} (رجوع فوق الكسر = فشل)\n⏱️ {now_str}")
            else:
                t = ACTIVE_TRADE
                trade_move = t.get("last_move", 20)
                timeout = 1200 if t.get("is_hero", False) else 2700
                if not t["tp1_hit"] and time.time() - t.get("entry_time", time.time()) > timeout:
                    profit = (price - t["entry"]) if t["type"] == "CALL" else (t["entry"] - price)
                    LAST_TRADE_CLOSE_TIME = time.time()
                    send_alert(f"⏰ <b>قفل - بدون حركة</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f} | النتيجة: {profit:+.2f}\n⏱️ {now_str}")
                    ACTIVE_TRADE = None
                    time.sleep(60)
                    continue

                if t["type"] == "CALL":
                    if price >= t["tp2"]:
                        old = t["tp2"]
                        t["sl"] = old - 4
                        t["tp1"] = old
                        t["tp2"] = old + trade_move
                        t["tp1_hit"] = True
                        send_alert(f"✅ <b>هدف تحقق {old:.2f} - خلك، جددت الهدف</b>\nالوقف المتحرك: {t['sl']:.2f} | 🎯 الهدف الجديد: {t['tp2']:.2f}\n⏱️ {now_str}")
                    elif price >= t["tp1"] and not t["tp1_hit"]:
                        t["tp1_hit"] = True
                        t["sl"] = t["entry"]
                        send_alert(f"🎯 <b>هدف 1 تحقق {t['tp1']:.2f} - خلك لا تبيع</b>\nالعقد: <code>{t['contract']}</code>\nحركت الوقف على الدخول\n⏱️ {now_str}")
                    elif price <= t["sl"]:
                        profit = price - t["entry"]
                        LAST_TRADE_CLOSE_TIME = time.time()
                        send_alert(f"🛑 <b>قفل الحين كامل</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f} | النتيجة: {profit:+.2f}\n⏱️ {now_str}")
                        ACTIVE_TRADE = None
                else:
                    if price <= t["tp2"]:
                        old = t["tp2"]
                        t["sl"] = old + 4
                        t["tp1"] = old
                        t["tp2"] = old - trade_move
                        t["tp1_hit"] = True
                        send_alert(f"✅ <b>هدف تحقق {old:.2f} - خلك، جددت الهدف</b>\nالوقف المتحرك: {t['sl']:.2f} | 🎯 الهدف الجديد: {t['tp2']:.2f}\n⏱️ {now_str}")
                    elif price <= t["tp1"] and not t["tp1_hit"]:
                        t["tp1_hit"] = True
                        t["sl"] = t["entry"]
                        send_alert(f"🎯 <b>هدف 1 تحقق {t['tp1']:.2f} - خلك لا تبيع</b>\nالعقد: <code>{t['contract']}</code>\nحركت الوقف على الدخول\n⏱️ {now_str}")
                    elif price >= t["sl"]:
                        profit = t["entry"] - price
                        LAST_TRADE_CLOSE_TIME = time.time()
                        send_alert(f"🛑 <b>قفل الحين كامل</b>\nالعقد: <code>{t['contract']}</code>\nدخول: {t['entry']:.2f} | إغلاق: {price:.2f} | النتيجة: {profit:+.2f}\n⏱️ {now_str}")
                        ACTIVE_TRADE = None

            time.sleep(60)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    monitor_market_dynamic()
