import asyncio
import requests
from telegram import Bot

# الإعدادات
TOKEN = "8633972708:AAGxG5GwbvvzyKPrcxAoU2hn90QJkiQttmA"
CHAT_ID = "-1003936661851"
bot = Bot(token=TOKEN)

# المعايير
MIN_PRICE, MAX_PRICE = 0.5, 6.0
MIN_CHANGE = 1.5
MIN_REL_VOL = 2.0

def fetch_stocks():
    url = "https://scanner.tradingview.com/america/scan"
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    payload = {
        "filter": [
            {"left": "close", "operation": "in_range", "right": [MIN_PRICE, MAX_PRICE]},
            {"left": "change", "operation": "egreater", "right": MIN_CHANGE},
            {"left": "relative_volume_24h", "operation": "egreater", "right": MIN_REL_VOL},
            {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]}
        ],
        "columns": ["name", "close", "change", "relative_volume_24h", "volume"]
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        # إرجاع البيانات إذا نجح الاتصال
        return res.json().get("data", [])
    except Exception as e:
        print(f"Error: {e}")
        return None  # إرجاع None للإشارة إلى وجود خطأ في الاتصال

async def main():
    print("--- Sniper Engine: Diagnostic Mode Active ---")
    await bot.send_message(chat_id=CHAT_ID, text="✅ *البوت في وضع التشخيص - سأبلغك بكل فحص*")
    
    while True:
        stocks = fetch_stocks()
        
        if stocks is not None:
            count = len(stocks)
            if count > 0:
                # البوت يرى أسهم
                msg = f"🔍 *فحص دوري:* تم العثور على {count} سهم يطابق معاييرك الدقيقة."
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
                
                # إرسال تفاصيل الأسهم (بحد أقصى 5 لتجنب إغراق القناة)
                for item in stocks[:5]:
                    d = item["d"]
                    await bot.send_message(chat_id=CHAT_ID, text=f"🚀 *سهم:* `{d[0]}` | السعر: `{d[1]}` | التغير: `+{d[2]}%`", parse_mode="Markdown")
            else:
                # البوت يرى السوق لكن لا توجد فرص تطابق المعايير الصارمة
                await bot.send_message(chat_id=CHAT_ID, text="❌ *فحص دوري:* البوت متصل، ولكن لا توجد أسهم تطابق المعايير حالياً.")
        else:
            # مشكلة في الاتصال بالسيرفر
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ *تحذير:* فشل الاتصال بسيرفرات تريدنق فيو (TradingView).")
            
        await asyncio.sleep(300) # فحص كل 5 دقائق

if __name__ == "__main__":
    asyncio.run(main())
