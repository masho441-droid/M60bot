import asyncio
import requests
from telegram import Bot

TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# --- معايير مخففة جداً للتجربة ---
# سنوسع النطاق ليشمل كل شيء تقريباً
MIN_PRICE, MAX_PRICE = 0.1, 500.0  # نطاق سعري واسع
MIN_CHANGE = 0.1                   # أقل حركة (0.1%)
MIN_REL_VOL = 0.5                  # أي سهم نشط قليلاً

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "change", "operation": "egreater", "right": MIN_CHANGE},
            {"left": "relative_volume_24h", "operation": "egreater", "right": MIN_REL_VOL}
        ],
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"],
        "options": {"lang": "en"}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json().get("data", [])
    except: return None

async def main():
    await bot.send_message(chat_id=CHAT_ID, text="🧪 *تم تشغيل وضع الاختبار (معايير مرنة).* سأرسل لك كل ما أجده!")
    
    while True:
        stocks = fetch_stocks()
        
        if stocks is not None:
            count = len(stocks)
            if count > 0:
                await bot.send_message(chat_id=CHAT_ID, text=f"🔍 *تم العثور على {count} سهم!* سأعرض لك أول 3 منها للتأكد من النظام:")
                for item in stocks[:3]:
                    d = item["d"]
                    await bot.send_message(chat_id=CHAT_ID, text=f"🚀 *سهم:* `{d[0]}` | السعر: `{d[1]}` | التغير: `+{d[2]}%`")
            else:
                await bot.send_message(chat_id=CHAT_ID, text="❌ *لا توجد أسهم حالياً.*")
        else:
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ *فشل الاتصال.*")
            
        await asyncio.sleep(120) # الفحص كل دقيقتين

if __name__ == "__main__":
    asyncio.run(main())
