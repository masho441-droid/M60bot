import asyncio
import time
import requests
from datetime import datetime
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

MIN_PRICE = 0.5
MAX_PRICE = 6.0
MIN_REL_VOL = 1.5
MIN_CHANGE = 1.0
MIN_TRADE_VALUE = 50000

last_values = {}
alert_counters = {}

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ: {e}")

def fetch_top_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"]
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        stocks = []
        for item in data.get("data", []):
            d = item["d"]
            if len(d) >= 5 and all(v is not None for v in d[1:5]):
                stocks.append({
                    "symbol": d[0],
                    "price": d[1],
                    "change": d[2],
                    "rel_vol": d[3],
                    "volume": d[4]
                })
        stocks.sort(key=lambda x: x["rel_vol"], reverse=True)
        return stocks[:100]
    except Exception as e:
        print(f"خطأ في جلب البيانات: {e}")
        return []

def calculate_strength(change, rel_vol, trade_value):
    score = 0
    score += min(change * 10, 35)
    score += min(rel_vol * 12, 30)
    if trade_value > 1000000:
        score += 20
    elif trade_value > 500000:
        score += 15
    elif trade_value > 200000:
        score += 10
    elif trade_value > 100000:
        score += 5
    return min(score, 100)

def get_targets(price, strength):
    if strength >= 80:
        return price * 1.08, price * 1.12, price * 1.18
    elif strength >= 60:
        return price * 1.05, price * 1.08, price * 1.12
    elif strength >= 40:
        return price * 1.03, price * 1.05, price * 1.07
    else:
        return price * 1.02, price * 1.03, price * 1.04

def get_success_rate(strength):
    if strength >= 85:
        return "85% - 95%"
    elif strength >= 70:
        return "75% - 85%"
    elif strength >= 55:
        return "65% - 75%"
    else:
        return "55% - 65%"

def get_strength_text(strength):
    if strength >= 85:
        return "💥 قوية جداً"
    elif strength >= 70:
        return "🚀 قوية"
    elif strength >= 55:
        return "📈 جيدة"
    else:
        return "👀 متوسطة"

def should_send_update(symbol, rel_vol, change):
    if symbol not in last_values:
        return True
    last = last_values[symbol]
    if rel_vol > last["rel_vol"] * 1.25 or change > last["change"] + 2:
        return True
    return False

async def main():
    await send_msg("✅ *تم تشغيل نظام رصد الاختراقات (نسخة موسعة)!*")
    print("--- البوت يعمل ---")

    while True:
        stocks = fetch_top_stocks()
        if not stocks:
            print("لا توجد بيانات، انتظر 30 ثانية...")
            await asyncio.sleep(30)
            continue

        for stock in stocks:
            symbol = stock["symbol"]
            price = stock["price"]
            change = stock["change"]
            rel_vol = stock["rel_vol"]
            volume = stock["volume"]
            trade_value = volume * price

            if change < MIN_CHANGE or rel_vol < MIN_REL_VOL or trade_value < MIN_TRADE_VALUE:
                continue

            if not should_send_update(symbol, rel_vol, change):
                continue

            last_values[symbol] = {"rel_vol": rel_vol, "change": change}
            alert_counters[symbol] = alert_counters.get(symbol, 0) + 1

            strength = calculate_strength(change, rel_vol, trade_value)
            t1, t2, t3 = get_targets(price, strength)
            success_rate = get_success_rate(strength)
            strength_text = get_strength_text(strength)
            trailing_stop = price * 0.98
            update_type = "تحديث زخم" if alert_counters[symbol] > 1 else "تنبيه أولي"
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            msg = (
                f"🔍 *اختراق واضح - {update_type}* 🔍\n\n"
                f"📌 **السهم:** `{symbol}` | 🔢 **تنبيه:** `#{alert_counters[symbol]}`\n"
                f"🕒 **الوقت:** `{current_time}` | 💵 **السعر:** `${price:.2f}`\n"
                f"📈 **الزخم:** `+{change:.2f}%` | 📊 **السيولة:** `{rel_vol:.1f}x`\n"
                f"💰 **قيمة التداول:** `${trade_value:,.0f}`\n"
                f"💪 **القوة:** `{strength_text}` (`{strength:.0f}/100`)\n\n"
                f"🎯 *الأهداف:*\n"
                f"1️⃣ **${t1:.2f}** (+{(t1/price-1)*100:.1f}%)\n"
                f"2️⃣ **${t2:.2f}** (+{(t2/price-1)*100:.1f}%)\n"
                f"3️⃣ **${t3:.2f}** (+{(t3/price-1)*100:.1f}%)\n\n"
                f"🛑 *وقف الخسارة:* `${trailing_stop:.2f}`\n"
                f"📈 *نسبة النجاح:* `{success_rate}`"
            )
            await send_msg(msg)
            await asyncio.sleep(1)

        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
