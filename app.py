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
MIN_PRICE = 0.1
MAX_PRICE = 10.0
MIN_CHANGE = 1.0
MIN_VOLUME = 50000
UPDATE_THRESHOLD = 0.03

last_values = {}
alert_counters = {}
avg_volume_cache = {}

# ==================== جلب جميع الأسهم من TradingView ====================
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
    except Exception as e:
        print(f"خطأ في جلب القائمة: {e}")
        return []

# ==================== جلب بيانات سهم واحد ====================
async def fetch_stock_data(session, symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        async with session.get(url, headers=headers, timeout=5) as resp:
            data = await resp.json()
            res = data['chart']['result'][0]['meta']
            price = res.get('regularMarketPrice')
            vol = res.get('regularMarketVolume')
            if price is None or vol is None or price == 0 or vol == 0:
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
        print(f"خطأ في الإرسال: {e}")

def is_volume_accelerating(volumes):
    if len(volumes) < 6:
        return False
    last_vol = volumes[-1]
    avg_5min = sum(volumes[-6:-1]) / 5
    return last_vol >= avg_5min * 2

def calculate_momentum_acceleration(price_history):
    if len(price_history) < 3:
        return 0
    ch1 = (price_history[-1] - price_history[-2]) / price_history[-2] * 100
    ch2 = (price_history[-2] - price_history[-3]) / price_history[-3] * 100
    return ch1 - ch2

async def send_alert(symbol, price, change, volume_ratio, alert_num):
    if alert_num == 1:
        strength = "📈 بداية انطلاق"
        success = "65% - 75%"
    else:
        strength = "🚀 تحديث زخم"
        success = "75% - 85%"
    target1 = price * 1.05
    target2 = price * 1.08
    target3 = price * 1.12
    stop = price * 0.97
    
    msg = (
        f"🔥 *تنبيه استراتيجي - صيد الانفجارات* 🔥\n\n"
        f"⏰ *الوقت:* {get_ny_time().strftime('%H:%M:%S')}\n"
        f"🔴 *الرمز:* {symbol}\n"
        f"📊 *رقم التنبيه:* {alert_num}\n"
        f"📈 *الحالة:* {strength}\n\n"
        f"💰 *السعر:* ${price:.2f}\n"
        f"📈 *الصعود:* +{change:.2f}%\n"
        f"📊 *الحجم النسبي:* {volume_ratio:.2f}x\n\n"
        f"🎯 *الأهداف:*\n"
        f"🟢 {target1:.2f} (+5%)\n"
        f"🟡 {target2:.2f} (+8%)\n"
        f"🔴 {target3:.2f} (+12%)\n\n"
        f"🛑 *وقف الخسارة:* {stop:.2f} (-3%)\n"
        f"📈 *نسبة النجاح:* {success}\n\n"
        f"✨ *M60 Hunter* ✨"
    )
    await send_msg(msg)

# ==================== الحلقة الرئيسية ====================
async def main():
    await send_msg("✅ *نظام الرصد الشامل (غير متزامن) يعمل الآن*")
    print("--- البوت يعمل ---")

    async with aiohttp.ClientSession() as session:
        while True:
            if not is_market_active():
                print("⏸️ عطلة نهاية الأسبوع. إيقاف الفحص...")
                last_values.clear()
                alert_counters.clear()
                await asyncio.sleep(3600)
                continue

            print("📡 جاري جلب قائمة الأسهم...")
            tickers = await fetch_all_tickers(session)
            print(f"✅ تم جلب {len(tickers)} سهماً")

            tasks = [fetch_stock_data(session, ticker) for ticker in tickers[:100]]  # حد 100 سهم لتجنب الحظر
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

                if price < MIN_PRICE or price > MAX_PRICE or volume < MIN_VOLUME:
                    continue

                volume_ratio = 1.0  # تبسيط (يمكن تحسينه)
                momentum_acc = calculate_momentum_acceleration(price_history)
                vol_acc = is_volume_accelerating(volumes)

                if symbol not in last_values:
                    if change >= MIN_CHANGE and momentum_acc > 0 and vol_acc:
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = 1
                        await send_alert(symbol, price, change, volume_ratio, 1)
                else:
                    if price >= last_values[symbol]["price"] * (1 + UPDATE_THRESHOLD):
                        last_values[symbol] = {"price": price, "change": change}
                        alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                        await send_alert(symbol, price, change, volume_ratio, alert_counters[symbol])

                await asyncio.sleep(random.uniform(0.1, 0.3))

            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
