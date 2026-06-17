import asyncio
import requests
from telegram import Bot

# --- الإعدادات ---
TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# --- محرك جلب البيانات ---
def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    # فلاتر متوازنة: سعر بين 0.5 و 10، تغير أكثر من 1%، سيولة مضاعفة
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [0.5, 10.0]},
            {"left": "change", "operation": "egreater", "right": 1.0},
            {"left": "relative_volume_24h", "operation": "egreater", "right": 1.5},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "options": {"lang": "en"},
        "columns": ["name", "close", "change", "relative_volume_24h"],
        "sort": {"sortBy": "relative_volume_24h", "sortOrder": "desc"}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json().get("data", [])
    except:
        return None

# --- الحلقة الرئيسية ---
async def main():
    await bot.send_message(chat_id=CHAT_ID, text="🤖 *البوت يعمل الآن - نظام المسح نشط*")
    
    while True:
        data = fetch_stocks()
        
        if data is not None:
            if len(data) > 0:
                msg = f"🔍 *تم العثور على {len(data)} فرصة:* \n"
                for item in data[:5]:
                    d = item["d"]
                    msg += f"• `{d[0]}`: {d[1]}$ | 📈 {d[2]}% | 📊 Vol: {d[3]:.1f}x\n"
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            else:
                # هذا يرسل تنبيهاً واحداً كل فترة لتعرف أنه يعمل بصمت
                print("Scanner active: No stocks matching criteria.")
        else:
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ *خطأ: فشل الاتصال بسيرفر السوق.*")
            
        await asyncio.sleep(120) # الفحص كل دقيقتين

if __name__ == "__main__":
    asyncio.run(main())
