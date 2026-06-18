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

# ==================== معايير المؤشرات الفورية ====================
MIN_PRICE = 0.5
MAX_PRICE = 5.0

# شروط المؤشرات (فورية)
MIN_VOLUME_RATIO = 1.5  # الشمعة الحالية > متوسط آخر 19 شمعة × 1.5
RSI_MIN = 45  # RSI فوق 45
VWAP_BUY = True  # السعر فوق VWAP
MA_ORDER = True  # MA10 > MA20 > MA50

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

# ==================== التحقق من أوقات العمل ====================
def is_trading_time():
    now = get_ny_time()
    current_time = now.time()
    
    pre_market_start = dt_time(4, 0)
    pre_market_end = dt_time(9, 30)
    regular_start = dt_time(9, 30)
    regular_end = dt_time(16, 0)
    after_hours_start = dt_time(16, 0)
    after_hours_end = dt_time(20, 0)

    is_pre = pre_market_start <= current_time < pre_market_end
    is_regular = regular_start <= current_time < regular_end
    is_after = after_hours_start <= current_time < after_hours_end

    return is_pre or is_regular or is_after

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
            
            # بيانات الشموع (5 دقائق)
            ohlcv = chart['indicators']['quote'][0]
            closes = [c for c in ohlcv.get('close', []) if c]
            highs = [h for h in ohlcv.get('high', []) if h]
            lows = [l for l in ohlcv.get('low', []) if l]
            volumes = [v for v in ohlcv.get('volume', []) if v]
            
            if not closes or not volumes:
                return None
            
            # السعر الحالي
            price = closes[-1] if closes else 0
            if not price:
                return None
            
            # التغير
            prev_close = res.get('regularMarketPreviousClose', price)
            change = ((price - prev_close) / prev_close) * 100
            
            # ==================== المؤشرات الفورية ====================
            
            # 1. الشمعة الحالية > متوسط آخر 19 شمعة × 1.5 (فوري)
            current_volume = volumes[-1] if volumes else 0
            if len(volumes) >= 20:
                avg_19_volume = sum(volumes[-20:-1]) / 19
            else:
                avg_19_volume = current_volume
            volume_ratio = current_volume / avg_19_volume if avg_19_volume > 0 else 1.0
            volume_signal = volume_ratio >= MIN_VOLUME_RATIO
            
            # 2. VWAP (من بداية الجلسة)
            vwap = 0
            if len(closes) >= 2:
                typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
                if sum(volumes) > 0:
                    vwap = sum(tp * v for tp, v in zip(typical_prices, volumes)) / sum(volumes)
            vwap_signal = price > vwap
            
            # 3. RSI (14 شمعة - فوري)
            rsi = 50
            if len(closes) >= 15:
                gains = []
                losses = []
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
            rsi_signal = rsi >= RSI_MIN
            
            # 4. ترتيب المتوسطات (فوري)
            ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else price
            ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else price
            ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else price
            ma_signal = ma10 > ma20 > ma50
            
            # قيمة التداول
            trade_value = price * current_volume
            
            return {
                "symbol": symbol,
                "price": price,
                "change": change,
                "volume": current_volume,
                "volume_ratio": volume_ratio,
                "vwap": vwap,
                "rsi": rsi,
                "ma10": ma10,
                "ma20": ma20,
                "ma50": ma50,
                "trade_value": trade_value,
                # المؤشرات المنطقية
                "volume_signal": volume_signal,
                "vwap_signal": vwap_signal,
                "rsi_signal": rsi_signal,
                "ma_signal": ma_signal
            }
    except Exception as e:
        print(f"خطأ في {symbol}: {e}")
        return None

# ==================== إرسال التنبيه ====================
async def send_alert(symbol, price, change, trade_value, volume_ratio, vwap, rsi, ma10, ma20, ma50, alert_num):
    now = get_ny_time().strftime("%H:%M:%S")
    
    # الأهداف الفنية
    resistance1 = price * 1.07
    resistance2 = price * 1.20
    support = price * 0.965
    
    # عدد الأسهم
    shares_available = int(trade_value / price) if price > 0 else 0
    
    # تحديد التوصية
    all_signals = all([volume_ratio >= 1.5, price > vwap, rsi >= 45, ma10 > ma20 > ma50])
    recommendation = "🔥 إشارة انفجار قوية - دخول فوري" if all_signals else "⏳ إشارة غير مكتملة - مراقبة"
    
    msg = (
        f"📊 *{symbol}* — {now}\n\n"
        f"🔹 *الرمز:* `{symbol}`\n"
        f"🔹 *نوع الحركة:* مؤشرات انفجار فورية\n"
        f"🔹 *عدد مرات التنبيه اليوم:* {alert_num} مرة\n"
        f"🔹 *نسبة الارتفاع:* `+{change:.2f}%`\n"
        f"🔹 *السعر الحالي:* `{price:.3f} دولار`\n"
        f"🔹 *عدد الأسهم المتاحة:* `{shares_available:,}`\n"
        f"🔹 *حجم السيولة:* `{trade_value/1000:.1f}K$`\n\n"
        f"📊 *المؤشرات الفورية:*\n"
        f"  • حجم الشمعة/متوسط 19: `{volume_ratio:.2f}x` {'✅' if volume_ratio >= 1.5 else '❌'}\n"
        f"  • السعر > VWAP: `{vwap:.3f}` ({'✅' if price > vwap else '❌'})\n"
        f"  • RSI (14): `{rsi:.1f}` ({'✅' if rsi >= 45 else '❌'})\n"
        f"  • ترتيب MA: `{ma10:.3f}` > `{ma20:.3f}` > `{ma50:.3f}` {'✅' if ma10 > ma20 > ma50 else '❌'}\n\n"
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
    await send_msg("✅ *بوت المؤشرات الفورية - انفجار سعري*")
    print("--- البوت يعمل بالمؤشرات الفورية ---")

    async with aiohttp.ClientSession() as session:
        while True:
            if not is_trading_time():
                now = get_ny_time().strftime("%H:%M:%S")
                print(f"⏸️ خارج أوقات التداول ({now}). انتظار 5 دقائق...")
                await asyncio.sleep(300)
                continue

            tickers = await fetch_all_tickers(session)
            print(f"📡 تم جلب {len(tickers)} سهماً")

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
                vwap = data["vwap"]
                rsi = data["rsi"]
                ma10 = data["ma10"]
                ma20 = data["ma20"]
                ma50 = data["ma50"]
                trade_value = data["trade_value"]
                
                volume_signal = data["volume_signal"]
                vwap_signal = data["vwap_signal"]
                rsi_signal = data["rsi_signal"]
                ma_signal = data["ma_signal"]

                # ✅ شروط المؤشرات الفورية (جميعها مجتمعة)
                if not (volume_signal and vwap_signal and rsi_signal and ma_signal):
                    continue

                # منطق التنبيه
                if symbol not in last_values:
                    last_values[symbol] = {"price": price, "change": change}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, trade_value, volume_ratio, vwap, rsi, ma10, ma20, ma50, 1)
                else:
                    if price >= last_values[symbol]["price"] * (1 + 0.02):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, trade_value, volume_ratio, vwap, rsi, ma10, ma20, ma50, alert_counters[symbol])

                await asyncio.sleep(random.uniform(0.3, 0.6))

            print(f"✅ انتهى الفحص. انتظار 30 ثانية...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
