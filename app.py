import os
import asyncio
import time
import yfinance as yf
from datetime import datetime
from telegram import Bot
from flask import Flask
import threading
import pytz

# ====================== CONFIG ==================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = Bot(token=TOKEN)
NY_TZ = pytz.timezone('America/New_York')
MAKKAH_TZ = pytz.timezone('Asia/Riyadh')

# ====================== STRATEGY SETTINGS ======================
MIN_PRICE = 0.5
MAX_PRICE = 10.0
# تم ضبط الحجم ليكون مرناً بناءً على وقت السوق
MIN_VOLUME_REGULAR = 500000
MIN_VOLUME_PRE = 100000 
MIN_CHANGE = 0.8
ALERT_COOLDOWN = 1800 

# ====================== FETCH DATA IN BATCHES ==================
async def fetch_data_batch(symbols):
    """جلب بيانات مجموعة أسهم مع تفعيل بيانات البري ماركت"""
    try:
        results = {}
        for symbol in symbols:
            try:
                # إضافة prepost=True هنا هو الجزء الأهم للبري ماركت
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1d", interval="1m", prepost=True)
                
                if not hist.empty:
                    current = hist.iloc[-1]
                    results[symbol] = {"price": current["Close"], "volume": current["Volume"]}
            except: continue
        return results
    except Exception as e:
        print(f"❌ خطأ في جلب البيانات: {e}")
        return {}

# ====================== LOGIC HELPER ============================
def is_premarket(now_makkah):
    # وقت البري ماركت بتوقيت نيويورك: 4:00 ص - 9:30 ص
    # بتوقيت مكة: 11:00 ص - 4:30 م
    ny_time = now_makkah.astimezone(NY_TZ)
    return 4 <= ny_time.hour < 9 or (ny_time.hour == 9 and ny_time.minute < 30)

# ====================== MAIN LOOP ===============================
async def main_loop():
    alert_history = {}
    print("🚀 M60 Hunter يعمل (وضع البري ماركت المفعل)...")
    
    while True:
        try:
            now_makkah = datetime.now(MAKKAH_TZ)
            current_min_volume = MIN_VOLUME_PRE if is_premarket(now_makkah) else MIN_VOLUME_REGULAR
            
            # جلب الرموز (تأكد من وجود دالة fetch_active_symbols هنا)
            symbols = await fetch_active_symbols_simple() 
            
            batch_size = 20
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i+batch_size]
                data_map = await fetch_data_batch(batch)
                
                for symbol, data in data_map.items():
                    price = data['price']
                    volume = data['volume']
                    
                    if MIN_PRICE <= price <= MAX_PRICE and volume >= current_min_volume:
                        if symbol not in alert_history or (time.time() - alert_history[symbol] > ALERT_COOLDOWN):
                            msg = (f"💥 *انفجار في {'[PRE]' if is_premarket(now_makkah) else '[REG]'} {symbol}*\n"
                                   f"💰 السعر: {price:.2f}\n📊 الحجم: {volume:,}")
                            await send_telegram(msg)
                            alert_history[symbol] = time.time()
                
                await asyncio.sleep(2) 
            
            await asyncio.sleep(60)
        except Exception as e:
            print(f"❌ خطأ: {e}")
            await asyncio.sleep(60)
