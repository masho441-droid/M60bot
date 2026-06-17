import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    
    # نطلب رموزاً محددة للتأكد من وصول البيانات من السيرفر
    payload = {
        "symbols": {
            "tickers": ["NASDAQ:AAPL", "NASDAQ:TSLA", "NASDAQ:AMD", "NYSE:F", "NYSE:GE"],
            "query": {"types": ["stock"]}
        },
        "columns": ["name", "close", "change"]
    }
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json().get("data", [])
    except Exception as e:
        print(f"DEBUG: {e}")
        return None

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="🧪 *بدء وضع التشخيص:* جارِ طلب بيانات أسهم محددة للتأكد من الاتصال..")
    
    while True:
        data = fetch_stocks()
        
        if data is not None:
            if len(data) > 0:
                msg = "✅ *تم استلام البيانات بنجاح:*\n"
                for item in data:
                    d = item["d"]
                    msg += f"• `{d[0]}`: {d[1]}$ (+{d[2]}%)\n"
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=CHAT_ID, text="❌ *البوت متصل، لكن لم يتم جلب أي بيانات للرموز المحددة.*")
        else:
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ *فشل الاتصال بسيرفر تريدنق فيو.*")
            
        await asyncio.sleep(60) # فحص كل دقيقة

if __name__ == "__main__":
    asyncio.run(main())
