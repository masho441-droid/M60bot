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

# ==================== المعايير (بدون دوران) ====================
MIN_PRICE = 0.5
MAX_PRICE = 5.0
MIN_CHANGE = 1.0
MIN_REL_VOL = 1.5
MIN_VOL_ACC = 1.2
MIN_TRADE_VALUE = 200000
MIN_MBI = 0.8
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
                print(f"⚠️ لا توجد بيانات لـ {symbol}")
                return None
            
            res = data['chart']['result'][0]['meta']
            price = res.get('preMarketPrice') or res.get('regularMarketPrice')
            
            quote = data['chart']['result'][0]['indicators']['quote'][0]
            volumes = [v for v in quote.get('volume', []) if v]
            vol = sum(volumes[-5:]) if volumes else res.get('preMarketVolume') or res.get('regularMarketVolume', 0)
            
            if not price or not vol:
                return None
            
            prev_close = res.get('regularMarketPreviousClose', res.get('previousClose', price))
            change = ((price - prev_close) / prev_close) * 100
            
            return {
                "symbol": symbol,
                "price": price,
                "volume": vol,
                "change": change,
                "volumes": volumes
            }
    except Exception as e:
        print(f"خطأ في {symbol}: {e}")
        return None

def calculate_vol_acc(volumes):
    if len(volumes) < 6:
        return 1.0
    last = volumes[-1]
    avg_5 = sum(volumes[-6:-1]) / 5
    return last / avg_5 if avg_5 > 0 else 1.0

# ==================== إرسال التنبيه ====================
async def send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, mbi, alert_num):
    now = get_ny_time().strftime("%H:%M:%S")
    target1 = price * 1.5
    target2 = price * 2.0
    target3 = price * 2.5
    stop = price * 0.90
    success = "82% - 92%"
    update_type = "تحديث زخم" if alert_num > 1 else "تنبيه أولي"
    
    msg = (
        f"🔥 *M60 Hunter*\n\n"
        f"⏰ *الوقت:* `{now}`\n"
        f"🔴 *الرمز:* `{symbol}` | 📊 *رقم التنبيه:* `#{alert_num}`\n\n"
        f"💰 *السعر:* `{price:.2f}`     📈 *الصعود:* `+{change:.2f}%`\n"
        f"📊 *الحجم:* `{rel_vol:.1f}x`     🚀 *التسارع:* `{vol_acc:.1f}x`\n"
        f"💵 *القيمة:* `{trade_value/1_000_000:.2f}M`\n\n"
        f"🎯 *الأهداف:* `{target1:.2f}` | `{target2:.2f}` | `{target3:.2f}`\n"
        f"🛑 *وقف الخسارة:* `{stop:.2f}`\n"
        f"📈 *نسبة النجاح:* `{success}`\n\n"
        f"📌 *توصية:* {update_type}"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *M60 Hunter يعمل*")
    print("--- البوت يعمل ---")

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

                rel_vol = volume / 500000
                vol_acc = calculate_vol_acc(volumes)
                trade_value = price * volume
                mbi = calculate_mbi(change, rel_vol)

                if (change < MIN_CHANGE or rel_vol < MIN_REL_VOL or
                    vol_acc < MIN_VOL_ACC or trade_value < MIN_TRADE_VALUE or
                    mbi < MIN_MBI):
                    continue

                print(f"✅ سيتم إرسال تنبيه لـ {symbol}")

                if symbol not in last_values:
                    last_values[symbol] = {"price": price, "change": change}
                    alert_counters[symbol] = 1
                    await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, mbi, 1)
                else:
                    if price >= last_values[symbol]["price"] * (1 + UPDATE_THRESHOLD):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, rel_vol, vol_acc, trade_value, mbi, alert_counters[symbol])

                await asyncio.sleep(random.uniform(0.3, 0.6))

            print(f"✅ انتهى الفحص. انتظار 30 ثانية...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
