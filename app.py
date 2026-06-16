import asyncio
import requests
from datetime import datetime
from telegram import Bot

# التأكد من صحة البيانات (البيانات المدخلة في المتغيرات أدناه يجب أن تكون دقيقة)
TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    # الـ Headers هي مفتاح نجاح الاتصال في Railway
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://www.tradingview.com/"
    }
    # الفلاتر مضبوطة وفق طلبك الأصلي
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [0.5, 6.0]},
            {"left": "change", "operation": "egreater", "right": 1.5},
            {"left": "relative_volume_24h", "operation": "egreater", "right": 2.0},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "options": {"lang": "en"},
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json().get("data", [])
    except:
        return []
    return []

async def main():
    while True:
        data = fetch_stocks()
        if data:
            for item in data:
                d = item["d"]
                # إرسال التنبيه مباشرة
                msg = f"🔍 *فرصة:* {d[0]}\n💵 السعر: {d[1]}\n📈 التغير: {d[2]}%"
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
