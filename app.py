import os
import asyncio
import aiohttp
import time
import random
from datetime import datetime
import pytz
from telegram import Bot

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
bot = Bot(token=TOKEN)

# ==================== المعايير الاحترافية (الصيد المبكر) ====================
MIN_PRICE = 0.5
MAX_PRICE = 8.0
MIN_CHANGE = 1.5
MIN_REL_VOL = 2.5
MIN_VOL_ACC = 2.0
MIN_TRADE_VALUE = 1_000_000
MIN_TURNOVER = 5.0
MIN_VOLUME = 100_000
MIN_MOMENTUM_ACC = 0.0
UPDATE_THRESHOLD = 0.03

last_values = {}
alert_counters = {}

# ==================== دوال مساعدة ====================
def get_ny_time():
    return datetime.now(pytz.timezone('America/New_York'))

def is_market_active():
    ny_now = get_ny_time()
    return ny_now.weekday() < 5

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ: {e}")

def calculate_success_rate(change, rel_vol, vol_acc, trade_value, turnover):
    score = 0
    score += min(change * 10, 30)
    score += min(rel_vol * 8, 25)
    score += min(vol_acc * 7, 20)
    score += 15 if trade_value > 1_000_000 else 10
    score += 10 if turnover > 5 else 5
    if score >= 85:
        return "85% - 95%"
    elif score >= 70:
        return "75% - 85%"
    elif score >= 55:
        return "65% - 75%"
    else:
        return "55% - 65%"

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
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=5) as resp:
            data = await resp.json()
            res = data['chart']['result'][0]['meta']
            price = res.get('regularMarketPrice')
            vol = res.get('regularMarketVolume')
            if not price or not vol or vol < MIN_VOLUME:
                return None
            prev = res.get('previousClose', price)
            change = ((price - prev) / prev) * 100
            volumes = [v for v in data['chart']['result'][0]['indicators']['quote'][0]['volume'] if v]
            price_history = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close'] if c]
            return {
                "symbol": symbol,
                "price": price,
                "volume": vol,
                "change": change,
                "volumes": volumes,
                "price_history": price_history
            }
    except:
        return None

def calculate_vol_acc(volumes):
    if len(volumes) < 6:
        return 1.0
    last = volumes[-1]
    avg_5 = sum(volumes[-6:-1]) / 5
    return last / avg_5 if avg_5 > 0 else 1.0

def calculate_momentum_acc(price_history):
    if len(price_history) < 3:
        return 0
    c1 = (price_history[-1] - price_history[-2]) / price_history[-2] * 100
    c2 = (price_history[-2] - price_history[-3]) / price_history[-3] * 100
    return c1 - c2

# ==================== إرسال التنبيه (نموذج 13-15 سطر) ====================
async def send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, turnover, alert_num):
    success_rate = calculate_success_rate(change, rel_vol, vol_acc, trade_value, turnover)
    target1 = price * 1.05
    target2 = price * 1.08
    target3 = price * 1.12
    stop = price * 0.97
    now = get_ny_time().strftime("%H:%M:%S")
    
    update_type = "تحديث زخم - دخول مع إعادة الاختبار" if alert_num > 1 else "تنبيه أولي - مراقبة"
    
    msg = (
        f"🔥 *M60 Hunter - صيد مبكر*\n\n"
        f"⏰ *الوقت:* `{now}`\n"
        f"🔴 *الرمز:* `{symbol}` | 📊 *رقم التنبيه:* `#{alert_num}`\n\n"
        f"💰 *السعر:* `{price:.2f}`     📈 *الصعود:* `+{change:.2f}%`\n"
        f"📊 *الحجم:* `{rel_vol:.1f}x`     🚀 *التسارع:* `{vol_acc:.1f}x`\n"
        f"💵 *القيمة:* `{trade_value/1_000_000:.2f}M`   📊 *الدوران:* `{turnover:.1f}%`\n\n"
        f"🎯 *الأهداف:* `{target1:.2f}` | `{target2:.2f}` | `{target3:.2f}`\n"
        f"🛑 *وقف الخسارة:* `{stop:.2f}`\n"
        f"📈 *نسبة النجاح:* `{success_rate}`\n\n"
        f"📌 *توصية:* {update_type}\n"
        f"✨ *M60 Hunter*"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *M60 Hunter - صيد مبكر مع سيولة حقيقية*")
    print("--- البوت يعمل ---")

    async with aiohttp.ClientSession() as session:
        while True:
            if not is_market_active():
                print("⏸️ عطلة نهاية الأسبوع. إيقاف الفحص...")
                await asyncio.sleep(3600)
                continue

            tickers = await fetch_all_tickers(session)
            print(f"📡 تم جلب {len(tickers)} سهماً")

            tasks = [fetch_stock_data(session, t) for t in tickers[:100]]
            results = await asyncio.gather(*tasks)

            for data in results:
                if not data:
                    continue

                symbol = data["symbol"]
                price = data["price"]
                volume = data["volume"]
                change = data["change"]
                volumes = data["volumes"]
                price_history = data["price_history"]

                rel_vol = volume / 500000
                vol_acc = calculate_vol_acc(volumes)
                momentum_acc = calculate_momentum_acc(price_history)
                trade_value = price * volume
                turnover = (volume / 1_000_000) * 100

                if (change < MIN_CHANGE or rel_vol < MIN_REL_VOL or
                    vol_acc < MIN_VOL_ACC or trade_value < MIN_TRADE_VALUE or
                    turnover < MIN_TURNOVER or momentum_acc < MIN_MOMENTUM_ACC):
                    continue

                if symbol not in last_values:
                    last_values[symbol] = {"price": price, "change": change}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, turnover, 1)
                else:
                    if price >= last_values[symbol]["price"] * (1 + UPDATE_THRESHOLD):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, turnover, alert_counters[symbol])

                await asyncio.sleep(random.uniform(0.3, 0.6))

            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
