import os
import asyncio
import alpaca_trade_api as tradeapi
from telegram import Bot

API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

bot = Bot(token=TOKEN)
api = tradeapi.REST(API_KEY, SECRET_KEY, "https://paper-api.alpaca.markets", api_version='v2')

async def main():
    tickers = ["AAPL", "TSLA", "NVDA", "AMD", "PLTR"]
    
    while True:
        try:
            msg = "📊 *أسعار السوق الحية:*\n\n"
            for ticker in tickers:
                quote = api.get_latest_quote(ticker)
                # التصحيح هنا: استخدام .ask.p بدلاً من .askprice
                price = quote.ask.p 
                msg += f"• `{ticker}`: {price}$\n"
            
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            print(f"حدث خطأ أثناء جلب البيانات: {e}")
            
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
