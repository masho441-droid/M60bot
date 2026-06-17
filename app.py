import os
import asyncio
import alpaca_trade_api as tradeapi
from telegram import Bot

# سحب المتغيرات
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

bot = Bot(token=TOKEN)
# استخدام Base URL صحيح
api = tradeapi.REST(API_KEY, SECRET_KEY, base_url="https://paper-api.alpaca.markets", api_version='v2')

async def main():
    tickers = ["AAPL", "TSLA", "NVDA"]
    while True:
        try:
            msg = "📊 أسعار الأسهم:\n"
            for ticker in tickers:
                quote = api.get_latest_quote(ticker)
                # استخدام الطريقة الآمنة للوصول للسعر
                price = getattr(quote, 'askprice', 'N/A')
                msg += f"{ticker}: {price}$\n"
            await bot.send_message(chat_id=CHAT_ID, text=msg)
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
