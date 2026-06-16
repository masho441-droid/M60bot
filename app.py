import asyncio
import requests
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# المعايير الأصلية الخاصة بك
MIN_PRICE = 0.5
MAX_PRICE = 6.0
MIN_CHANGE = 1.5
MIN_REL_VOL = 2.0
MIN_TRADE_VALUE = 100000

last_values = {}
alert_counters = {}

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ في إرسال التليجرام: {e}")

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    # تحسين الهوية لجلب البيانات بثبات
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://www.tradingview.com/"
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
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            stocks = []
            for item in data.get("data", []):
                d = item["d"]
                price, change, rel_vol, vol = d[1], d[2], d[3], d[4]
                trade_value = price * vol
                if trade_value >= MIN_TRADE_VALUE:
                    stocks.append({"symbol": d[0], "price": price, "change": change, "rel_vol": rel_vol, "trade_value": trade_value})
            return stocks
    except Exception as e:
        print(f"خطأ جلب البيانات: {e}")
    return []

# --- الدوال الأصلية الخاصة بك ---
def calculate_strength(change, rel_vol, trade_value):
    score = min(change * 10, 35) + min(rel_vol * 12, 30)
    score += 20 if trade_value > 1000000 else (15 if trade_value > 500000 else 10)
    return min(score, 100)

def get_targets(price, strength):
    if strength >= 80: return price * 1.08, price * 1.12, price * 1.18
    if strength >= 60: return price * 1.05, price * 1.08, price * 1.12
    return price * 1.03, price * 1.05, price * 1.07

def get_success_rate(strength):
    return "85% - 95%" if strength >= 85 else ("75% - 85%" if strength >= 70 else "65% - 75%")

def get_strength_text(strength):
    return "💥 قوية جداً" if strength >= 85 else ("🚀 قوية" if strength >= 70 else "📈 جيدة")

async def main():
    print("--- البوت يعمل الآن ---")
    while True:
        stocks = fetch_stocks()
        for stock in stocks:
            strength = calculate_strength(stock['change'], stock['rel_vol'], stock['trade_value'])
            t1, t2, t3 = get_targets(stock['price'], strength)
            msg = (f"🔍 *اختراق جديد:* `{stock['symbol']}`\n"
                   f"💵 السعر: `${stock['price']:.2f}` | 📈 الزخم: `+{stock['change']:.2f}%`\n"
                   f"💪 القوة: {get_strength_text(strength)} (`{strength:.0f}/100`)\n"
                   f"🎯 الأهداف: `{t1:.2f} - {t2:.2f} - {t3:.2f}`")
            await send_msg(msg)
        await asyncio.sleep(60) # زيادة التوقيت لضمان عدم الحظر

if __name__ == "__main__":
    asyncio.run(main())
