import logging, time, requests, os
from datetime import datetime, timezone
import pandas as pd

logger = logging.getLogger(__name__)
ACTIVE_TRADE = None
LAST_ALERT = 0
LAST_TRADE_CLOSE_TIME = 0

def fetch_yahoo(symbol, range_, interval="1m"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, params={"range": range_, "interval": interval, "includePrePost": "true"}, timeout=10)
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
        logger.error(f"Data error {symbol}: {e}")
        return None

def get_spx_1m():
    return fetch_yahoo("^GSPC", "1d")

def get_es_1m():
    return fetch_yahoo("ES=F", "5d")

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
    logger.info("SPX + ES 24h FIXED - Spread + Gap")
    send_alert("✅ <b>البوت اشتغل - 24 ساعة حقيقي</b>\nبالنهار SPX | بالليل ES | فرق السعر مخصوم | دخول الجاب")

    while True:
        try:
            df_spx = get_spx_1m()
            df_es_raw = get_es_1m()
            if df_es_raw is None or len(df_es_raw) < 80:
                time.sleep(60)
                continue
            if df_spx is None or len(df_spx) < 10:
                df_spx = None

            utc_now = datetime.now(timezone.utc)
            month = utc_now.month
            ny_offset = -5 if month in [11, 12, 1, 2, 3] else -4
            ny_hour = (utc_now.hour + ny_offset) % 24
            ny_time = ny_hour * 60 + utc_now.minute
            is_hero_time = ny_time >= 840 and ny_time < 960
            is_cash_open = ny_time >= 570 and ny_time < 960  # 9:30 - 16:00 نيويورك

            # === إصلاح 1+2: حساب فرق ES - SPX وتعديل ES ===
            # نأخذ آخر وقت لـ SPX، ونشوف سعر ES بنفس الوقت، الفرق هذا هو الـ Spread
            spread = 10.0
            if df_spx is not None:
                spx_last_time = df_spx['time'].iloc[-1]
                # أقرب شمعة ES لوقت إغلاق SPX
                idx = (df_es_raw['time'] - spx_last_time).abs().idxmin()
                spread = float(df_es_raw['close'].iloc[idx] - df_spx['close'].iloc[-1])

            # نسخة ES معدلة = ES - Spread = سعر مكافئ لـ SPX
            df_es = df_es_raw.copy()
            for col in ['open', 'high', 'low', 'close']:
                df_es[col] = df_es[col] - spread

            # === اختيار مصدر السعر حسب الوقت ===
            # بالنهار: SPX، بالليل: ES المعدل
            if is_cash_open and df_spx is not None and len(df_spx) >= 80:
                df = df_spx
                source = "SPX"
            else:
                # بالليل نستخدم آخر 400 شمعة من ES المعدل، عشان القمم تكون قريبة
                df = df_es.tail(400).reset_index(drop=True)
                source = "ES-ليل"

            price = float(df['close'].iloc[-1])
            prev_price = float(df['close'].iloc[-2])
            open_price = float(df['open'].iloc[-1])
            now_str = datetime.now().strftime("%H:%M:%S")

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

            # القمم من المصدر الحالي (SPX بالنهار، ES المعدل بالليل)
            spx_highs, spx_lows = get_swing_levels(df)
            last_swing_high = spx_highs[-1][1] if spx_highs else None
            last_swing_low = spx_lows[-1][1] if spx_lows else None

            # الأهداف: قمم المصدر الحالي + قمم ES المعدلة (للأهداف البعيدة)
            es_highs_raw, es_lows_raw = get_swing_levels(df_es)
            all_highs_vals = [h for _, h in spx_highs] + [h for _, h in es_highs_raw[-10:]]
            all_lows_vals = [l for _, l in spx_lows] + [l for _, l in es_lows_raw[-10:]]
            all_highs_vals = sorted(set(all_highs_vals))
            all_lows_vals = sorted(set(all_lows_vals))

            last_move = 20
            if len(spx_highs) >= 1 and len(spx_lows) >= 1:
                if spx_highs[-1][0] > spx_lows[-1][0]:
                    last_move = abs(spx_highs[-1][1] - spx_lows[-1][1])
                else:
                    last_move = abs(spx_lows[-1][1] - spx_highs[-1][1])
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
                        for h in all_highs_vals:
                            if h > tp1:
                                tp2 = h
                                break
                        ACTIVE_TRADE = {"type": "CALL", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": hero_low, "tp1_hit": False, "entry_time": time.time(), "is_hero": True, "last_move": compress_height}
                        LAST_ALERT = time.time()
                        send_alert(f"🔥 <b>دخول HERO CALL - اختراق انضغاط</b>\n<b>السعر {source}:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر انضغاط: {hero_high:.2f} | طول الانضغاط: {compress_height:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f}\n🎯 هدف 2: {tp2:.2f}\n🛑 وقف: {hero_low:.2f}\n⏱️ {now_str}")
                    elif hero_put and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW P {base - 25}"
                        tp1 = hero_low - compress_height
                        tp2 = tp1 - compress_height
                        for l in reversed(all_lows_vals):
                            if l < tp1:
                                tp2 = l
                                break
                        ACTIVE_TRADE = {"type": "PUT", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": hero_high, "tp1_hit": False, "entry_time": time.time(), "is_hero": True, "last_move": compress_height}
                        LAST_ALERT = time.time()
                        send_alert(f"🔥 <b>دخول HERO PUT - كسر انضغاط</b>\n<b>السعر {source}:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر انضغاط: {hero_low:.2f} | طول الانضغاط: {compress_height:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f}\n🎯 هدف 2: {tp2:.2f}\n🛑 وقف: {hero_high:.2f}\n⏱️ {now_str}")
                else:
                    if is_chop:
                        time.sleep(60)
                        continue
                    up_trend = ema9 > ema21 and ema21 > ema50
                    down_trend = ema9 < ema21 and ema21 < ema50

                    # === إصلاح 3: دخول الجاب ===
                    normal_call = price > last_swing_high and prev_price <= last_swing_high + 1
                    gap_call = price > last_swing_high and open_price > last_swing_high  # فتح فوق القمة = جاب
                    normal_put = price < last_swing_low and prev_price >= last_swing_low - 1
                    gap_put = price < last_swing_low and open_price < last_swing_low  # فتح تحت القاع = جاب

                    call_break = (normal_call or gap_call) and price > vwap
                    put_break = (normal_put or gap_put) and price < vwap

                    vwap_up = vwap > prev_vwap
                    vwap_down = vwap < prev_vwap
                    is_call = up_trend and call_break and vwap_up and vol_ok
                    is_put = down_trend and put_break and vwap_down and vol_ok
                    if is_call and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW C {base + 5}"
                        candidates = [h for h in all_highs_vals if h > price + 2]
                        tp1 = min(candidates) if candidates else last_swing_high + last_move
                        tp2 = last_swing_high + last_move
                        if tp2 <= tp1:
                            tp2 = tp1 + last_move
                        sl = min(float(df['low'].iloc[-1]), last_swing_high - 2)
                        ACTIVE_TRADE = {"type": "CALL", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": sl, "tp1_hit": False, "entry_time": time.time(), "is_hero": False, "last_move": last_move}
                        LAST_ALERT = time.time()
                        gap_txt = " (جاب)" if gap_call else ""
                        send_alert(f"🚨 <b>دخول CALL{gap_txt} - اختراق قمة</b>\n<b>السعر {source}:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر قمة: {last_swing_high:.2f} | طول الحركة: {last_move:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f}\n🎯 هدف 2: {tp2:.2f}\n🛑 وقف: {sl:.2f}\n⏱️ {now_str}")
                    elif is_put and time.time() - LAST_ALERT > 60:
                        base = round(price / 5) * 5
                        contract = f"SPXW P {base - 5}"
                        candidates = [l for l in all_lows_vals if l < price - 2]
                        tp1 = max(candidates) if candidates else last_swing_low - last_move
                        tp2 = last_swing_low - last_move
                        if tp2 >= tp1:
                            tp2 = tp1 - last_move
                        sl = max(float(df['high'].iloc[-1]), last_swing_low + 2)
                        ACTIVE_TRADE = {"type": "PUT", "contract": contract, "entry": price, "tp1": tp1, "tp2": tp2, "sl": sl, "tp1_hit": False, "entry_time": time.time(), "is_hero": False, "last_move": last_move}
                        LAST_ALERT = time.time()
                        gap_txt = " (جاب)" if gap_put else ""
                        send_alert(f"🚨 <b>دخول PUT{gap_txt} - كسر قاع</b>\n<b>السعر {source}:</b> {price:.2f} | <b>VWAP:</b> {vwap:.2f}\nكسر قاع: {last_swing_low:.2f} | طول الحركة: {last_move:.1f}\n<b>العقد:</b> <code>{contract}</code>\n🎯 هدف 1: {tp1:.2f}\n🎯 هدف 2: {tp2:.2f}\n🛑 وقف: {sl:.2f}\n⏱️ {now_str}")
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
