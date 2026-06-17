import asyncio
import yfinance as yf
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# ==================== قائمة موسعة (NASDAQ 100 + S&P 500) ====================
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "JPM", "V",
    "WMT", "JNJ", "PG", "UNH", "HD", "MA", "DIS", "ADBE", "NFLX", "CRM",
    "AMD", "INTC", "PEP", "COST", "CSCO", "ABT", "TMO", "ACN", "NKE", "QCOM",
    "IBM", "ORCL", "TXN", "AMAT", "LRCX", "MU", "ADI", "SNPS", "CDNS",
    "SBUX", "BKNG", "MDLZ", "CMCSA", "F", "GE", "BA", "CAT", "CVX", "XOM",
    "KO", "PFE", "MRK", "LLY", "ABBV", "BMY", "AMGN", "GILD", "REGN", "VRTX",
    "SPGI", "ICE", "MCO", "ADP", "PAYX", "CTSH", "C", "GS", "MS", "SCHW",
    "BLK", "BK", "TFC", "USB", "PNC", "COF", "AXP", "COF", "DHR", "DE",
    "HON", "MMM", "UPS", "RTX", "LMT", "NOC", "GD", "T", "TMUS", "CCI",
    "PLD", "WELL", "SPG", "PSA", "O", "DOC", "DUK", "SO", "NEE", "D",
    "AEP", "EXC", "ED", "AWK", "PEG", "XEL", "CL", "KMB", "PM", "MO",
    "STZ", "MNST", "TAP", "BF.B", "SAM", "MKC", "HUM", "CI", "CNC", "ANTM",
    "MOH", "AET", "CVS", "WBA", "ABC", "TGT", "LOW", "M", "KSS", "JWN",
    "TJX", "ROST", "DG", "DLTR", "EBAY", "ETSY", "EXPE", "TRIP"
]

# ==================== المعايير ====================
MIN_CHANGE = 1.0
MIN_REL_VOL = 1.5
MIN_TRADE_VALUE = 100000

last_values = {}
alert_counters = {}

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ: {e}")

def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        data = stock.history(period="2d")
        if len(data) < 2:
            return None
        prev_close = data['Close'].iloc[-2]
        current = data.iloc[-1]
        price = current['Close']
        volume = current['Volume']
        change = ((price - prev_close) / prev_close) * 100
        avg_volume = data['Volume'].mean()
        rel_vol = volume / avg_volume if avg_volume > 0 else 1
        trade_value = price * volume
        if change >= MIN_CHANGE and rel_vol >= MIN_REL_VOL and trade_value >= MIN_TRADE_VALUE:
            return {
                "symbol": symbol,
                "price": price,
                "change": change,
                "rel_vol": rel_vol,
                "volume": volume,
                "trade_value": trade_value
            }
    except Exception as e:
        print(f"خطأ في {symbol}: {e}")
    return None

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

def should_send_update(symbol, rel_vol, change):
    if symbol not in last_values:
        return True
    last = last_values[symbol]
    if rel_vol > last["rel_vol"] * 1.25 or change > last["change"] + 2:
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *البوت جاهز ويعمل الآن (Yahoo Finance)*\n\n"
        f"📊 يراقب {len(TICKERS)} سهماً\n"
        "🔍 يبحث عن اختراقات وفق المعايير\n"
        "📈 يرسل جميع الإشارات مع متابعة الأسهم\n\n"
        "🚀 تداول موفق",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 *حالة البوت*\n"
        f"✅ يعمل\n"
        f"⏱️ فحص كل 60 ثانية\n"
        f"📈 عدد التنبيهات: {sum(alert_counters.values())}",
        parse_mode="Markdown"
    )

async def main():
    await send_msg("✅ *تم تشغيل نظام رصد الاختراقات (Yahoo Finance) بنجاح!*")
    print("--- البوت يعمل ---")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("--- أوامر البوت مفعلة ---")

    while True:
        candidates = []
        for symbol in TICKERS:
            stock = get_stock_data(symbol)
            if stock:
                candidates.append(stock)

        if not candidates:
            print("لا توجد فرص حالياً.")
            await asyncio.sleep(60)
            continue

        candidates.sort(key=lambda x: x["rel_vol"], reverse=True)

        for stock in candidates[:5]:
            if not should_send_update(stock['symbol'], stock['rel_vol'], stock['change']):
                continue

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

        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
