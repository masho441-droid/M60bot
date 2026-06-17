import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    # تغيير الـ Headers ليكون أكثر محاكاة لمتصفح حقيقي (تجنب الحظر)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
        "Content-Type": "application/json"
    }
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [0.5, 20.0]},
            {"left": "change", "operation": "egreater", "right": 0.5}
        ],
        "options": {"lang": "en"},
        "columns": ["name", "close", "change"],
        "sort": {"sortBy": "change", "sortOrder": "desc"},
        "range": [0, 10]
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json().get("data", [])
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        return None

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="🚀 *محرك البحث الجديد يعمل.. أنتظر البيانات الآن*")
    while True:
        data = fetch_stocks()
        if data is not None:
            if len(data) > 0:
                msg = "🔍 *أسهم نشطة الآن في السوق:*\n"
                for item in data[:5]:
                    d = item["d"]
                    msg += f"• `{d[0]}`: {d[1]}$ (+{d[2]}%)\n"
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=CHAT_ID, text="⚠️ *البوت متصل ولكن لا توجد أسهم تطابق الفلتر البسيط.*")
        else:
            await bot.send_message(chat_id=CHAT_ID, text="❌ *فشل الاتصال بسيرفر البيانات.*")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
