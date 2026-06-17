import os
import asyncio
import alpaca_trade_api as tradeapi
from telegram import Bot

# سحب الإعدادات من المتغيرات في Railway
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

# إعداد الاتصال
bot = Bot(token=TOKEN)
api = tradeapi.REST(API_KEY, SECRET_KEY, "https://paper-api.alpaca.markets", api_version='v2')

async def main():
    try:
        await bot.send_message(chat_id=CHAT_ID, text="✅ *تم تشغيل البوت بنجاح - مراقبة السوق مفعلة*")
    except Exception as e:
        print(f"خطأ في إرسال رسالة الترحيب: {e}")

    # الأسهم المراد مراقبتها
    tickers = ["AAPL", "TSLA", "NVDA", "AMD", "PLTR"]
    
    while True:
        try:
            msg = "📊 *تحديث أسعار الأسهم اللحظي:*\n\n"
            for ticker in tickers:
                quote = api.get_latest_quote(ticker)
                # السعر الحالي من Alpaca
                msg += f"• `{ticker}`: {quote.askprice}$\n"
            
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        except Exception as e:
            print(f"حدث خطأ أثناء جلب البيانات: {e}")
            
        # الانتظار لمدة 5 دقائق (300 ثانية)
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
