import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# سنقوم بمراقبة قائمة ثابتة من الأسهم النشطة جداً
WATCHLIST = ["NASDAQ:AAPL", "NASDAQ:TSLA", "NASDAQ:AMD", "NASDAQ:NVDA", "NASDAQ:PLTR"]

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="✅ *تم تشغيل البوت بنظام مراقبة القوائم المباشر.*")
    
    while True:
        try:
            # استخدام API مباشر للحصول على الأسعار الحالية
            url = "https://quote.tradingview.com/quotes"
            params = {"symbols": ",".join(WATCHLIST)}
            res = requests.get(url, params=params, timeout=10)
            data = res.json()
            
            msg = "📊 *تحديث الأسعار الآن:*\n"
            for item in data.get("quotes", []):
                name = item["symbol"]
                price = item["lp"] # Last Price
                change = item["ch"] # Change
                msg += f"• `{name}`: {price}$ ({change}%)\n"
            
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            
        except Exception as e:
            print(f"Error: {e}")
            
        await asyncio.sleep(300) # تحديث كل 5 دقائق

if __name__ == "__main__":
    asyncio.run(main())
