import time
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

def main():
    try:
        bot.send_message(chat_id=CHAT_ID, text="✅ البوت يعمل الآن (بداية جديدة)")
        print("تم الإرسال بنجاح")
    except Exception as e:
        print(f"خطأ: {e}")

    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
