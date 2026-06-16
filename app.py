import asyncio
import time
import yfinance as yf
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# قائمة الأسهم
TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ: {e}")

async def main():
    await send_msg("✅ *البوت يعمل الآن (Yahoo Finance)*")
    print("--- البوت يعمل ---")

    while True:
        for symbol in TICKERS:
            try:
                stock = yf.Ticker(symbol)
                data = stock.history(period="1d")
                if not data.empty:
                    price = data['Close'].iloc[-1]
                    volume = data['Volume'].iloc[-1]
                    msg = (
                        f"📊 *{symbol}*\n"
                        f"💰 السعر: ${price:.2f}\n"
                        f"📊 الحجم: {volume:,}\n"
                        f"🕒 {datetime.now().strftime('%H:%M:%S')}"
                    )
                    await send_msg(msg)
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"خطأ في {symbol}: {e}")
        print("انتظار 60 ثانية...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
