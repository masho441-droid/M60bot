import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# --- استراتيجيتك الأصلية ---
MIN_PRICE = 0.5
MAX_PRICE = 6.0
MIN_CHANGE = 1.5
MIN_REL_VOL = 2.0
MIN_TRADE_VALUE = 100000

def calculate_strength(change, rel_vol, trade_value):
    score = min(change * 10, 35) + min(rel_vol * 12, 30)
    score += 20 if trade_value > 1000000 else (15 if trade_value > 500000 else 10)
    return min(score, 100)

def get_targets(price, strength):
    if strength >= 80: return price * 1.08, price * 1.12, price * 1.18
    if strength >= 60: return price * 1.05, price * 1.08, price * 1.12
    return price * 1.03, price * 1.05, price * 1.07

def get_strength_text(strength):
    return "💥 قوية جداً" if strength >= 85 else ("🚀 قوية" if strength >= 70 else "📈 جيدة")

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "change", "operation": "egreater", "right": MIN_CHANGE},
            {"left": "relative_volume_24h", "operation": "egreater", "right": MIN_REL_VOL},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"]
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json().get("data", [])
    except: return []

async def main():
    print("--- Sniper Engine: Full Strategy Active ---")
    await bot.send_message(chat_id=CHAT_ID, text="✅ *البوت يعمل الآن بكامل استراتيجيتك!*")
    
    while True:
        stocks = fetch_stocks()
        for item in stocks:
            d = item["d"]
            symbol, price, change, rel_vol, vol = d[0], d[1], d[2], d[3], d[4]
            trade_value = price * vol
            
            if trade_value >= MIN_TRADE_VALUE:
                strength = calculate_strength(change, rel_vol, trade_value)
                t1, t2, t3 = get_targets(price, strength)
                
                msg = (f"🔍 *فرصة اختراق:* `{symbol}`\n"
                       f"💵 السعر: `${price:.2f}` | 📈 الزخم: `+{change:.2f}%`\n"
                       f"💪 القوة: {get_strength_text(strength)} (`{strength:.0f}/100`)\n"
                       f"🎯 الأهداف: `{t1:.2f} - {t2:.2f} - {t3:.2f}`")
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        
        await asyncio.sleep(60) # الفحص كل دقيقة

if __name__ == "__main__":
    asyncio.run(main())
