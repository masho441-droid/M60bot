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

# ==================== معايير الاستراتيجية ====================
MIN_PRICE = 0.5
MAX_PRICE = 5.0
MIN_CHANGE = 0.3  # نسبة الارتفاع 0.3%
MIN_REL_VOL = 0.3  # الحجم النسبي 0.3X
MIN_TRADE_VALUE = 100_000  # سيولة 100K$
UPDATE_THRESHOLD = 0.02  # تحديث عند تحرك 2%

# نسب الأهداف الفنية (ديناميكية)
RESISTANCE_1_RATIO = 1.07  # مقاومة 1 = سعر + 7%
RESISTANCE_2_RATIO = 1.20  # مقاومة 2 = سعر + 20%
SUPPORT_RATIO = 0.965  # الدعم = سعر - 3.5%

# ==================== مؤشر قوة الاندفاع ====================
VSR_STRONG = 2.5  # اندفاع قوي جداً (دخول فوري)
VSR_GOOD = 2.0    # اندفاع جيد (دخول مع وقف ضيق)
VSR_MEDIUM = 1.5  # اندفاع متوسط (انتظار اختراق)

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
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=5) as resp:
            data = await resp.json()
            
            if not data.get('chart', {}).get('result'):
                return None
            
            res = data['chart']['result'][0]['meta']
            
            # السعر الحالي
            price = res.get('preMarketPrice') or res.get('regularMarketPrice')
            
            quote = data['chart']['result'][0]['indicators']['quote'][0]
            volumes = [v for v in quote.get('volume', []) if v]
            
            # الحجم الإجمالي (آخر 5 شموع)
            vol = sum(volumes[-5:]) if volumes else res.get('preMarketVolume') or res.get('regularMarketVolume', 0)
            
            if not price or not vol:
                return None
            
            prev_close = res.get('regularMarketPreviousClose', res.get('previousClose', price))
            change = ((price - prev_close) / prev_close) * 100
            
            # حجم أول دقيقة
            first_minute_vol = volumes[0] if volumes and len(volumes) > 0 else 0
            
            # القيمة السوقية
            market_cap = res.get('marketCap', 0)
            
            return {
                "symbol": symbol,
                "price": price,
                "volume": vol,
                "change": change,
                "volumes": volumes,
                "prev_close": prev_close,
                "first_minute_vol": first_minute_vol,
                "market_cap": market_cap
            }
    except Exception as e:
        print(f"خطأ في {symbol}: {e}")
        return None

def calculate_vol_acc(volumes):
    """تسارع الحجم (آخر شمعة مقارنة بمتوسط 5 شموع سابقة)"""
    if len(volumes) < 6:
        return 1.0
    last = volumes[-1]
    avg_5 = sum(volumes[-6:-1]) / 5
    return last / avg_5 if avg_5 > 0 else 1.0

def calculate_vsr(volumes):
    """
    قوة الاندفاع (Volume Surge Ratio)
    = حجم أول دقيقة ÷ متوسط حجم آخر 5 دقائق
    """
    if len(volumes) < 6:
        return 1.0
    first_minute = volumes[0] if volumes else 0
    avg_5 = sum(volumes[-5:]) / 5 if volumes else 1
    return first_minute / avg_5 if avg_5 > 0 else 1.0

def get_vsr_status(vsr):
    """تحديد حالة قوة الاندفاع"""
    if vsr >= VSR_STRONG:
        return "🔥 اندفاع قوي جداً (دخول فوري)"
    elif vsr >= VSR_GOOD:
        return "✅ اندفاع جيد (دخول مع وقف ضيق)"
    elif vsr >= VSR_MEDIUM:
        return "⏳ اندفاع متوسط (انتظار اختراق)"
    else:
        return "📉 اندفاع ضعيف (مراقبة فقط)"

# ==================== إرسال التنبيه ====================
async def send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, market_cap, first_minute_vol, alert_num, vsr):
    now = get_ny_time().strftime("%H:%M:%S")
    
    # حساب الأهداف الفنية (ديناميكية)
    resistance1 = price * RESISTANCE_1_RATIO
    resistance2 = price * RESISTANCE_2_RATIO
    support = price * SUPPORT_RATIO
    
    # عدد الأسهم المتاحة
    shares_available = int(trade_value / price) if price > 0 else 0
    
    # حجم السيولة بالألف
    liquidity = trade_value / 1000
    
    # حالة قوة الاندفاع
    vsr_status = get_vsr_status(vsr)
    
    # تحديد نوع التنبيه
    if alert_num == 1:
        alert_type = "زخم شرائي 5 دقائق"
    else:
        alert_type = f"تحديث زخم #{alert_num}"
    
    msg = (
        f"📊 *{symbol}* — {now}\n\n"
        f"🔹 *الرمز:* `{symbol}`\n"
        f"🔹 *نوع الحركة:* {alert_type}\n"
        f"🔹 *عدد مرات التنبيه اليوم:* {alert_num} مرة\n"
        f"🔹 *نسبة الارتفاع:* `+{change:.1f}%`\n"
        f"🔹 *السعر الحالي:* `{price:.3f} دولار`\n"
        f"🔹 *عدد الأسهم المتاحة للتداول:* `{shares_available:,}`\n"
        f"🔹 *القيمة السوقية:* `{market_cap/1_000_000:.1f}M`\n"
        f"🔹 *الحجم النسبي:* `{rel_vol:.1f}X`\n"
        f"🔹 *حجم أول دقيقة:* `{first_minute_vol:,}`\n"
        f"🔹 *حجم السيولة:* `{liquidity:.1f}K$`\n"
        f"🔹 *قوة الاندفاع:* `{vsr:.1f}x` {vsr_status}\n\n"
        f"🎯 *الأهداف الفنية:*\n"
        f"  • مقاومة 1: `{resistance1:.3f} دولار`\n"
        f"  • مقاومة 2: `{resistance2:.3f} دولار`\n"
        f"  • الدعم: `{support:.3f} دولار`\n\n"
        f"⏰ *التوقيت الأمريكي:* `{now}`"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *بوت زخم 5 دقائق - قوة الاندفاع*")
    print("--- البوت يعمل بالاستراتيجية المطورة ---")

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
                volume = data["volume"]
                change = data["change"]
                volumes = data["volumes"]
                first_minute_vol = data["first_minute_vol"]
                market_cap = data["market_cap"]

                # حساب المؤشرات
                rel_vol = volume / 500000  # حجم نسبي مقارنة بـ 500K
                vol_acc = calculate_vol_acc(volumes)
                trade_value = price * volume
                vsr = calculate_vsr(volumes)  # قوة الاندفاع

                # ✅ شروط الاستراتيجية
                if change < MIN_CHANGE:
                    continue
                if rel_vol < MIN_REL_VOL:
                    continue
                if trade_value < MIN_TRADE_VALUE:
                    continue
                if price < MIN_PRICE or price > MAX_PRICE:
                    continue

                # منطق التنبيه
                if symbol not in last_values:
                    last_values[symbol] = {"price": price, "change": change}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, market_cap, first_minute_vol, 1, vsr)
                else:
                    # تحديث عند تحرك 2%
                    if price >= last_values[symbol]["price"] * (1 + UPDATE_THRESHOLD):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, market_cap, first_minute_vol, alert_counters[symbol], vsr)

                await asyncio.sleep(random.uniform(0.3, 0.6))

            print(f"✅ انتهى الفحص. انتظار 30 ثانية...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
