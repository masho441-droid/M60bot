import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

async def send_msg(text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error: {e}")

async def main():
    print("--- البوت يعمل الآن (Sniper Mode) ---")
    # إرسال رسالة تجريبية للتأكد من وصول التنبيهات
    await send_msg("✅ *تم تفعيل البوت - يبحث عن اختراقات الآن...*")
    
    while True:
        # هنا ستضع كود الجلب (fetch_stocks) كما كان
        # إذا لم تجد أسهم، سيستمر البوت بالعمل بصمت دون توقف
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
