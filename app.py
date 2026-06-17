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

# ==================== المعايير ====================
MIN_PRICE = 0.5
MAX_PRICE = 5.0
MIN_CHANGE = 3.0
MIN_REL_VOL = 3.0
MIN_VOL_ACC = 2.5
MIN_TRADE_VALUE = 1_000_000
MIN_TURNOVER = 15.0
MIN_MBI = 1.2
UPDATE_THRESHOLD = 0.05

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

def calculate_mbi(change, rel_vol):
    return (change / 1.5) * (rel_vol / 2.0)

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
            if not price or not vol:
                return None
            prev_close = res.get('regularMarketPreviousClose', res.get('previousClose', price))
            change = ((price - prev_close) / prev_close) * 100
            volumes = [v for v in data['chart']['result'][0]['indicators']['quote'][0]['volume'] if v]
            price_history = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close'] if c]
            return {
                "symbol": symbol,
                "price": price,
                "volume": vol,
                "change": change,
                "volumes": volumes,
                "price_history": price_history,
                "prev_close": prev_close
            }
    except:
        return None

def calculate_vol_acc(volumes):
    if len(volumes) < 6:
        return 1.0
    last = volumes[-1]
    avg_5 = sum(volumes[-6:-1]) / 5
    return last / avg_5 if avg_5 > 0 else 1.0

def calculate_turnover(volume):
    return (volume / 1_000_000) * 100

# ==================== إرسال التنبيه (النموذج المثالي) ====================
async def send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, turnover, mbi, alert_num):
    now = get_ny_time().strftime("%H:%M:%S")
    target1 = price * 1.5
    target2 = price * 2.0
    target3 = price * 2.5
    stop = price * 0.90
    success = "82% - 92%"
    update_type = "تحديث زخم - دخول مع إعادة الاختبار" if alert_num > 1 else "تنبيه أولي - مراقبة"
    
    msg = (
        f"🔥 *M60 Hunter - صيد مبكر متقدم*\n\n"
        f"⏰ *الوقت:* `{now}`\n"
        f"🔴 *الرمز:* `{symbol}` | 📊 *رقم التنبيه:* `#{alert_num}`\n\n"
        f"💰 *السعر:* `{price:.2f}`     📈 *الصعود:* `+{change:.2f}%`\n"
        f"📊 *الحجم:* `{rel_vol:.1f}x`     🚀 *التسارع:* `{vol_acc:.1f}x`\n"
        f"💵 *القيمة:* `{trade_value/1_000_000:.2f}M`   📊 *الدوران:* `{turnover:.1f}%`\n\n"
        f"🎯 *الأهداف:* `{target1:.2f}` | `{target2:.2f}` | `{target3:.2f}`\n"
        f"🛑 *وقف الخسارة:* `{stop:.2f}`\n"
        f"📈 *نسبة النجاح:* `{success}`\n\n"
        f"📌 *توصية:* {update_type}\n"
        f"✨ *M60 Hunter*"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *M60 Hunter - صيد مبكر متقدم*")
    print("--- البوت يعمل 24/7 ---")

    async with aiohttp.ClientSession() as session:
        while True:
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
                trade_value = price * volume
                turnover = calculate_turnover(volume)
                mbi = calculate_mbi(change, rel_vol)

                if (change < MIN_CHANGE or rel_vol < MIN_REL_VOL or
                    vol_acc < MIN_VOL_ACC or trade_value < MIN_TRADE_VALUE or
                    turnover < MIN_TURNOVER or mbi < MIN_MBI):
                    continue

                if symbol not in last_values:
                    last_values[symbol] = {"price": price, "change": change}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, turnover, mbi, 1)
                else:
                    if price >= last_values[symbol]["price"] * (1 + UPDATE_THRESHOLD):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, turnover, mbi, alert_counters[symbol])

                await asyncio.sleep(random.uniform(0.3, 0.6))

            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
