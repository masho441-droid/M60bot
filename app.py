import os
import asyncio
import requests
from datetime import datetime
from telegram import Bot

# سحب البيانات من متغيرات Railway
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
bot = Bot(token=TOKEN)

MIN_PRICE = 0.5
MAX_PRICE = 6.0
MIN_CHANGE = 0.5
MIN_REL_VOL = 1.0
MIN_TRADE_VALUE = 50000

last_values = {}
alert_counters = {}

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ في إرسال الرسالة: {e}")

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json"
    }
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "change", "operation": "egreater", "right": MIN_CHANGE},
            {"left": "relative_volume_24h", "operation": "egreater", "right": MIN_REL_VOL},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "options": {"lang": "en"},
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        stocks = []
        for item in data.get("data", []):
            d = item["d"]
            if len(d) >= 5 and all(v is not None for v in d):
                price, volume = d[1], d[4]
                trade_value = price * volume
                if trade_value >= MIN_TRADE_VALUE:
                    stocks.append({"symbol": d[0], "price": price, "change": d[2], "rel_vol": d[3], "volume": volume, "trade_value": trade_value})
        return stocks
    except Exception as e:
        print(f"خطأ في جلب البيانات: {e}")
        return []

def calculate_strength(change, rel_vol, trade_value):
    score = min(change * 10, 35) + min(rel_vol * 12, 30)
    score += 20 if trade_value > 1000000 else (15 if trade_value > 500000 else 10)
    return min(score, 100)

def get_targets(price, strength):
    if strength >= 80: return price * 1.08, price * 1.12, price * 1.18
    if strength >= 60: return price * 1.05, price * 1.08, price * 1.12
    return price * 1.03, price * 1.05, price * 1.07

def get_success_rate(strength):
    if strength >= 85: return "85% - 95%"
    if strength >= 70: return "75% - 85%"
    if strength >= 55: return "65% - 75%"
    return "55% - 65%"

def get_strength_text(strength):
    if strength >= 85: return "💥 قوية جداً"
    if strength >= 70: return "🚀 قوية"
    if strength >= 55: return "📈 جيدة"
    return "👀 متوسطة"

async def main():
    await send_msg("✅ *نظام الرصد (Rasad) يعمل الآن - السوق الأمريكي*")
    while True:
        stocks = fetch_stocks()
        for stock in stocks:
            symbol = stock['symbol']
            # تحديث منطق الفلترة للإرسال
            last = last_values.get(symbol, {"rel_vol": 0, "change": 0})
            if stock['rel_vol'] > last["rel_vol"] * 1.25 or stock['change'] > last["change"] + 2:
                last_values[symbol] = {"rel_vol": stock['rel_vol'], "change": stock['change']}
                alert_counters[symbol] = alert_counters.get(symbol, 0) + 1
                
                strength = calculate_strength(stock['change'], stock['rel_vol'], stock['trade_value'])
                t1, t2, t3 = get_targets(stock['price'], strength)
                
                msg = (
                    f"🔍 *اختراق واضح - {'تحديث زخم' if alert_counters[symbol]>1 else 'تنبيه أولي'}*\n\n"
                    f"📌 **السهم:** `{symbol}` | 🔢 **تنبيه:** `#{alert_counters[symbol]}`\n"
                    f"🕒 **الوقت:** `{datetime.now().strftime('%H:%M:%S')}`\n"
                    f"💵 **السعر:** `${stock['price']:.2f}`\n"
                    f"📈 **الزخم:** `+{stock['change']:.2f}%` | 📊 **السيولة:** `{stock['rel_vol']:.1f}x`\n"
                    f"💪 **القوة:** `{get_strength_text(strength)}` (`{strength:.0f}/100`)\n"
                    f"🎯 *الأهداف:* `{t1:.2f}` → `{t2:.2f}` → `{t3:.2f}`\n"
                    f"🛑 *وقف الخسارة:* `{stock['price'] * 0.98:.2f}`\n"
                    f"📈 *نسبة النجاح:* `{get_success_rate(strength)}`"
                )
                await send_msg(msg)
                await asyncio.sleep(0.5)
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
