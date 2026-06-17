import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# --- معايير الفلتر ---
MIN_PRICE, MAX_PRICE = 0.5, 6.0
MIN_CHANGE = 1.5
MIN_REL_VOL = 2.0

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
    print("--- Sniper Engine: Active & Reporting ---")
    await bot.send_message(chat_id=CHAT_ID, text="✅ *تم تشغيل البوت - سأرسل تقريراً بعد كل عملية فحص*")
    
    while True:
        stocks = fetch_stocks()
        
        if stocks:
            for item in stocks:
                d = item["d"]
                msg = (f"🔍 *فرصة اختراق:* `{d[0]}`\n"
                       f"💵 السعر: `${d[1]:.2f}` | 📈 الزخم: `+{d[2]:.2f}%`\n"
                       f"📊 السيولة: `{d[3]:.1f}x`")
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        else:
            # رسالة الحالة (يمكنك حذف هذا الجزء لاحقاً إذا أزعجك كثرة الرسائل)
            await bot.send_message(chat_id=CHAT_ID, text="🔍 *فحص دوري:* لا توجد أسهم تطابق المعايير حالياً.")
            
        await asyncio.sleep(300) # الفحص كل 5 دقائق لتقليل عدد الرسائل

if __name__ == "__main__":
    asyncio.run(main())
