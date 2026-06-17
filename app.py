import asyncio
import time
import requests
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# ==================== المعايير ====================
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
        print(f"خطأ: {e}")

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
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
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        stocks = []
        for item in data.get("data", []):
            d = item["d"]
            if len(d) >= 5 and all(v is not None for v in d):
                price = d[1]
                volume = d[4]
                trade_value = price * volume
                if trade_value >= MIN_TRADE_VALUE:
                    stocks.append({
                        "symbol": d[0],
                        "price": price,
                        "change": d[2],
                        "rel_vol": d[3],
                        "volume": volume,
                        "trade_value": trade_value
                    })
        return stocks
    except Exception as e:
        print(f"خطأ في جلب البيانات: {e}")
        return []

def calculate_strength(change, rel_vol, trade_value):
    score = min(change * 10, 35) + min(rel_vol * 12, 30)
    score += 20 if trade_value > 1000000 else (15 if trade_value > 500000 else 10)
    return min(score, 100)

def get_targets(price, strength):
    if strength >= 80:
        return price * 1.08, price * 1.12, price * 1.18
    if strength >= 60:
        return price * 1.05, price * 1.08, price * 1.12
    return price * 1.03, price * 1.05, price * 1.07

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

# ==================== منع التكرار (معلق حالياً) ====================
def should_send_update(symbol, rel_vol, change):
    if symbol not in last_values:
        return True
    last = last_values[symbol]
    if rel_vol > last["rel_vol"] * 1.25 or change > last["change"] + 2:
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *البوت جاهز ويعمل الآن*\n\n"
        "📊 يراقب جميع الأسهم الأمريكية\n"
        "🔍 يبحث عن اختراقات وفق المعايير\n"
        "📈 يرسل جميع الإشارات مع متابعة الأسهم\n\n"
        "🚀 تداول موفق",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 *حالة البوت*\n"
        f"✅ يعمل\n"
        f"⏱️ فحص كل 30 ثانية\n"
        f"📈 عدد التنبيهات: {sum(alert_counters.values())}",
        parse_mode="Markdown"
    )

async def main():
    await send_msg("✅ *تم تشغيل نظام رصد الاختراقات بنجاح!*")
    print("--- البوت يعمل ---")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("--- أوامر البوت مفعلة ---")

    while True:
        stocks = fetch_stocks()
        if not stocks:
            print("لا توجد فرص حالياً.")
            await asyncio.sleep(30)
            continue

        print(f"تم العثور على {len(stocks)} فرصة")
        for stock in stocks:
            # ==================== تم تعطيل شرط منع التكرار ====================
            # if not should_send_update(stock['symbol'], stock['rel_vol'], stock['change']):
            #     continue

            last_values[stock['symbol']] = {"rel_vol": stock['rel_vol'], "change": stock['change']}
            alert_counters[stock['symbol']] = alert_counters.get(stock['symbol'], 0) + 1

            strength = calculate_strength(stock['change'], stock['rel_vol'], stock['trade_value'])
            t1, t2, t3 = get_targets(stock['price'], strength)
            success_rate = get_success_rate(strength)
            strength_text = get_strength_text(strength)
            trailing_stop = stock['price'] * 0.98
            update_type = "تحديث زخم" if alert_counters[stock['symbol']] > 1 else "تنبيه أولي"
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            msg = (
                f"🔍 *اختراق واضح - {update_type}* 🔍\n\n"
                f"📌 **السهم:** `{stock['symbol']}` | 🔢 **تنبيه:** `#{alert_counters[stock['symbol']]}`\n"
                f"🕒 **الوقت:** `{current_time}` | 💵 **السعر:** `${stock['price']:.2f}`\n"
                f"📈 **الزخم:** `+{stock['change']:.2f}%` | 📊 **السيولة:** `{stock['rel_vol']:.1f}x`\n"
                f"💰 **قيمة التداول:** `${stock['trade_value']:,.0f}`\n"
                f"💪 **القوة:** `{strength_text}` (`{strength:.0f}/100`)\n\n"
                f"🎯 *الأهداف:*\n"
                f"1️⃣ **${t1:.2f}** (+{(t1/stock['price']-1)*100:.1f}%)\n"
                f"2️⃣ **${t2:.2f}** (+{(t2/stock['price']-1)*100:.1f}%)\n"
                f"3️⃣ **${t3:.2f}** (+{(t3/stock['price']-1)*100:.1f}%)\n\n"
                f"🛑 *وقف الخسارة:* `${trailing_stop:.2f}`\n"
                f"📈 *نسبة النجاح:* `{success_rate}`"
            )
            await send_msg(msg)
            await asyncio.sleep(0.5)

        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
