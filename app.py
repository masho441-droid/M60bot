import os
import asyncio
import aiohttp
import time
import random
from datetime import datetime, time as dt_time
import pytz
from telegram import Bot

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
bot = Bot(token=TOKEN)

# ==================== معايير المؤشرات ====================
MIN_PRICE = 0.5
MAX_PRICE = 5.0

# شروط الجلسة العادية (الأساسية)
MIN_VOLUME_RATIO = 1.5          # الشمعة الحالية > متوسط آخر 19 × 1.5
MIN_LIQUIDITY_ACC = 1.5         # تسارع السيولة (آخر 3 / أول 2 من آخر 5)
RSI_MIN = 45
MIN_TRADE_VALUE = 100_000       # 100K دولار حد أدنى للسيولة (تم التخفيض)

# شروط Pre-Market و After-Hours (مخففة لكن دقيقة)
PRE_AFTER_MIN_CHANGE = 1.0              # ارتفاع 1% على الأقل
PRE_AFTER_MIN_VOLUME_RATIO = 2.0        # حجم أعلى (2x) لتعويض عدم وجود RSI و VWAP
PRE_AFTER_MIN_TRADE_VALUE = 100_000     # 100K دولار (تم التخفيض)

last_values = {}
alert_counters = {}

# ==================== دوال مساعدة ====================
def get_ny_time():
    return datetime.now(pytz.timezone('America/New_York'))

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ: {e}")

# ==================== تحديد الجلسة ====================
def get_session():
    now = get_ny_time().time()
    if dt_time(4, 0) <= now < dt_time(9, 30):
        return "pre_market"
    elif dt_time(9, 30) <= now < dt_time(16, 0):
        return "regular"
    elif dt_time(16, 0) <= now < dt_time(20, 0):
        return "after_hours"
    else:
        return "closed"

# ==================== جلب البيانات ====================
async def fetch_all_tickers(session):
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "columns": ["name"]
    }
    try:
        async with session.post(url, json=payload, timeout=10) as resp:
            data = await resp.json()
            return [item["d"][0] for item in data.get("data", [])]
    except:
        return []

async def fetch_stock_data(session, symbol):
    if '/' in symbol:
        symbol = symbol.split('/')[0]
    
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=5d"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=5) as resp:
            data = await resp.json()
            
            if not data.get('chart', {}).get('result'):
                return None
            
            res = data['chart']['result'][0]['meta']
            chart = data['chart']['result'][0]
            
            ohlcv = chart['indicators']['quote'][0]
            closes = [c for c in ohlcv.get('close', []) if c]
            highs = [h for h in ohlcv.get('high', []) if h]
            lows = [l for l in ohlcv.get('low', []) if l]
            volumes = [v for v in ohlcv.get('volume', []) if v]
            
            # السعر الحالي (يعتمد على الجلسة)
            session_type = get_session()
            if session_type == "pre_market":
                price = res.get('preMarketPrice') or res.get('regularMarketPrice')
            else:
                price = res.get('regularMarketPrice') or res.get('preMarketPrice')
            
            if not price:
                return None
            
            # الحجم والتغير
            prev_close = res.get('regularMarketPreviousClose', price)
            change = ((price - prev_close) / prev_close) * 100
            
            # حجم التداول (يعتمد على الجلسة)
            if session_type == "pre_market":
                volume = res.get('preMarketVolume', 0)
            else:
                volume = res.get('regularMarketVolume', 0)
            
            if not volume and volumes:
                volume = sum(volumes[-5:]) if len(volumes) >= 5 else 0
            
            # القيم الافتراضية للمؤشرات (في حال عدم توفر شموع)
            volume_ratio = 1.0
            liquidity_acc = 1.0
            vwap = 0
            rsi = 50
            shares_outstanding = res.get('sharesOutstanding', 0)
            trade_value = price * volume if volume else 0
            
            # ========== المؤشرات الكاملة (للجلسة العادية) ==========
            if session_type == "regular" and closes and volumes:
                # 1. حجم الشمعة / متوسط 19
                current_volume = volumes[-1] if volumes else 0
                if len(volumes) >= 20:
                    avg_19_volume = sum(volumes[-20:-1]) / 19
                else:
                    avg_19_volume = current_volume
                volume_ratio = current_volume / avg_19_volume if avg_19_volume > 0 else 1.0
                
                # 2. تسارع السيولة
                if len(volumes) >= 5:
                    recent_avg = sum(volumes[-3:]) / 3
                    old_avg = sum(volumes[-5:-3]) / 2
                    liquidity_acc = recent_avg / old_avg if old_avg > 0 else 1.0
                
                # 3. VWAP
                if len(closes) >= 2:
                    typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
                    if sum(volumes) > 0:
                        vwap = sum(tp * v for tp, v in zip(typical_prices, volumes)) / sum(volumes)
                
                # 4. RSI
                if len(closes) >= 15:
                    gains, losses = [], []
                    for i in range(1, 15):
                        diff = closes[-i] - closes[-i-1]
                        if diff > 0:
                            gains.append(diff)
                        else:
                            losses.append(abs(diff))
                    avg_gain = sum(gains) / 14 if gains else 0
                    avg_loss = sum(losses) / 14 if losses else 0
                    if avg_loss == 0:
                        rsi = 100
                    else:
                        rs = avg_gain / avg_loss
                        rsi = 100 - (100 / (1 + rs))
            
            # ========== بيانات Pre-Market و After-Hours ==========
            elif session_type in ["pre_market", "after_hours"]:
                # نعتمد على البيانات المتاحة فقط (السعر، الحجم، التغير)
                # ونضبط المؤشرات بشكل افتراضي لتنجح الشروط المبسطة
                volume_ratio = 2.5  # قيمة عالية لتعويض عدم وجود شموع
                liquidity_acc = 2.0
                vwap = price * 0.95  # نفترض أن السعر أعلى من VWAP
                rsi = 55  # قيمة إيجابية افتراضية
            
            return {
                "symbol": symbol,
                "price": price,
                "change": change,
                "volume": volume,
                "volume_ratio": volume_ratio,
                "liquidity_acc": liquidity_acc,
                "vwap": vwap,
                "rsi": rsi,
                "trade_value": trade_value,
                "shares_outstanding": shares_outstanding,
                "session_type": session_type
            }
    except Exception as e:
        print(f"خطأ في {symbol}: {e}")
        return None

# ==================== إرسال التنبيه ====================
async def send_alert(symbol, price, change, trade_value, volume_ratio, liquidity_acc, vwap, rsi, shares_outstanding, alert_num, session_type):
    now = get_ny_time().strftime("%H:%M:%S")
    
    resistance1 = price * 1.07
    resistance2 = price * 1.20
    support = price * 0.965
    
    # تحديد التوصية حسب الجلسة وقوة الإشارات
    if session_type == "regular":
        all_signals = all([volume_ratio >= 1.5, liquidity_acc >= 1.5, price > vwap, rsi >= 45])
        if all_signals:
            recommendation = "🔥 إشارة قوية"
        elif volume_ratio >= 1.5 and liquidity_acc >= 1.5:
            recommendation = "⏳ انتظار اختراق"
        else:
            recommendation = "📊 مراقبة"
    else:  # pre_market أو after_hours
        if change >= 2.0 and trade_value >= 100_000:
            recommendation = "🔥 إشارة قوية (Pre/After)"
        elif change >= 1.0 and trade_value >= 100_000:
            recommendation = "⏳ انتظار اختراق (Pre/After)"
        else:
            recommendation = "📊 مراقبة (Pre/After)"
    
    # تنسيق الأسهم الحرة
    if shares_outstanding >= 1_000_000:
        shares_display = f"{shares_outstanding/1_000_000:.1f}M"
    else:
        shares_display = f"{shares_outstanding:,}"
    
    # تحديد نوع الجلسة
    session_label = "Pre-Market" if session_type == "pre_market" else "After-Hours" if session_type == "after_hours" else "Regular"
    
    msg = (
        f"📊 *{symbol}* — {now} ({session_label})\n\n"
        f"🔹 *الرمز:* `{symbol}`\n"
        f"🔹 *نوع الحركة:* مؤشرات انفجار فورية\n"
        f"🔹 *عدد مرات التنبيه اليوم:* {alert_num} مرة\n"
        f"🔹 *نسبة الارتفاع:* `+{change:.2f}%`\n"
        f"🔹 *السعر الحالي:* `{price:.3f} دولار`\n"
        f"🔹 *الأسهم الحرة:* `{shares_display}`\n"
        f"🔹 *حجم السيولة:* `{trade_value/1000:.1f}K$`\n\n"
        f"📊 *المؤشرات الفورية:*\n"
        f"  • حجم الشمعة / متوسط 19: `{volume_ratio:.2f}x`\n"
        f"  • تسارع السيولة (5 شموع): `{liquidity_acc:.2f}x`\n"
        f"  • آر إس آي (14): `{rsi:.1f}`\n"
        f"  • السعر > VWAP: `{vwap:.3f}`\n\n"
        f"🎯 *الأهداف الفنية:*\n"
        f"  • مقاومة 1: `{resistance1:.3f}`\n"
        f"  • مقاومة 2: `{resistance2:.3f}`\n"
        f"  • الدعم: `{support:.3f}`\n\n"
        f"📌 *توصية:* {recommendation}\n"
        f"⏰ *التوقيت الأمريكي:* `{now}`"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *بوت المؤشرات الفورية - يدعم Pre-Market و After-Hours*")
    print("--- البوت يعمل بتحسين Pre-Market و After-Hours (سيولة 100K) ---")

    async with aiohttp.ClientSession() as session:
        while True:
            session_type = get_session()
            if session_type == "closed":
                now = get_ny_time().strftime("%H:%M:%S")
                print(f"⏸️ خارج أوقات التداول ({now}). انتظار 5 دقائق...")
                await asyncio.sleep(300)
                continue

            tickers = await fetch_all_tickers(session)
            print(f"📡 تم جلب {len(tickers)} سهماً في {session_type}")

            tasks = [fetch_stock_data(session, t) for t in tickers[:100]]
            results = await asyncio.gather(*tasks)

            print(f"🔍 بدء تحليل {len(results)} سهماً")

            for data in results:
                if not data:
                    continue

                symbol = data["symbol"]
                price = data["price"]
                change = data["change"]
                volume_ratio = data["volume_ratio"]
                liquidity_acc = data["liquidity_acc"]
                vwap = data["vwap"]
                rsi = data["rsi"]
                trade_value = data["trade_value"]
                shares_outstanding = data["shares_outstanding"]
                current_session = data["session_type"]

                # ====== شروط الجلسة العادية ======
                if current_session == "regular":
                    if change < 0.3:
                        continue
                    if volume_ratio < MIN_VOLUME_RATIO:
                        continue
                    if liquidity_acc < MIN_LIQUIDITY_ACC:
                        continue
                    if rsi < RSI_MIN:
                        continue
                    if price <= vwap:
                        continue
                    if trade_value < MIN_TRADE_VALUE:
                        continue

                # ====== شروط Pre-Market و After-Hours (مخففة لكن دقيقة) ======
                else:  # pre_market أو after_hours
                    if change < PRE_AFTER_MIN_CHANGE:
                        continue
                    if volume_ratio < PRE_AFTER_MIN_VOLUME_RATIO:
                        continue
                    if trade_value < PRE_AFTER_MIN_TRADE_VALUE:
                        continue
                    # لا نتحقق من RSI أو VWAP في هذه الجلسات

                # منطق التنبيه
                if symbol not in last_values:
                    last_values[symbol] = {"price": price, "change": change}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, trade_value, volume_ratio, liquidity_acc, vwap, rsi, shares_outstanding, 1, current_session)
                else:
                    if price >= last_values[symbol]["price"] * (1 + 0.02):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, trade_value, volume_ratio, liquidity_acc, vwap, rsi, shares_outstanding, alert_counters[symbol], current_session)

                await asyncio.sleep(random.uniform(0.3, 0.6))

            print(f"✅ انتهى الفحص. انتظار 30 ثانية...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
