import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    
    # الفلاتر التي تستهدف الاختراقات الحقيقية
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [0.5, 6.0]},
            {"left": "change", "operation": "egreater", "right": 1.5},
            {"left": "relative_volume_24h", "operation": "egreater", "right": 2.0},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "columns": ["name", "close", "change", "volume", "relative_volume_24h"],
        "sort": {"sortBy": "relative_volume_24h", "sortOrder": "desc"}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json().get("data", [])
    except: return []

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="🚀 *Sniper Engine: تم استعادة محرك القنص بنجاح.* أراقب السوق الآن..")
    while True:
        data = fetch_stocks()
        if data:
            msg = "🎯 *فرص اختراق مكتشفة الآن:*\n"
            for item in data[:5]:
                d = item["d"]
                msg += f"• `{d[0]}`: {d[1]}$ | 📈 {d[2]}% | 📊 Vol: {d[4]:.0f}\n"
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        else:
            # رسالة لا تظهر إلا إذا لم يجد شيئاً ليؤكد لك أن المحرك لا يزال يعمل
            print("Scanner active: No breakouts found currently.")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
