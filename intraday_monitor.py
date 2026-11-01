import logging
import time
import requests
import yfinance as yf
import os
from datetime import datetime
from telegram import Bot
from level_engine import get_daily_bars, calculate_pivot_levels

logger = logging.getLogger(__name__)

# تتبع التنبيهات
LAST_ALERTS = {}

def get_spx_price():
    try:
        ticker = yf.Ticker("^GSPC")
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return data['Close'].iloc[-1]
        return None
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return None

def get_recommended_strike(price, direction):
    if direction == "CALL":
        strike = round(price / 5) * 5 + 5
        return f"SPXW C {strike}"
    elif direction == "PUT":
        strike = round(price / 5) * 5 - 5
        return f"SPXW P {strike}"

def monitor_market():
    bot = Bot(token=os.environ.get("TELEGRAM_BOT_TOKEN"))
    logger.info("Intraday Monitor Started (24/7)...")
    
    while True:
        try:
            bars = get_daily_bars()
            if not bars:
                time.sleep(60)
                continue
                
            levels = calculate_pivot_levels(bars)
            current_price = get_spx_price()
            if current_price is None or not levels:
                time.sleep(60)
                continue
            
            # فحص كل مستوى
            for level_name, level_price in levels.items():
                dist = abs(current_price - level_price)
                # المسافة 0.05%
                if dist <= (current_price * 0.0005):
                    if LAST_ALERTS.get(level_name) != "Alerted":
                        call_contract = get_recommended_strike(current_price, "CALL")
                        put_contract = get_recommended_strike(current_price, "PUT")
                        
                        msg = f"""
🚨 <b>اقتراب من مستوى {level_name} ({level_price:.2f})</b>
<b>السعر:</b> {current_price:.2f}

📈 <b>خطة الاختراق (CALL):</b>
• العقد: <code>{call_contract}</code>
• الهدف: {level_price + 15:.2f}
• الوقف: {level_price - 8:.2f}

📉 <b>خطة الفشل (PUT):</b>
• العقد: <code>{put_contract}</code>
• الهدف: {level_price - 15:.2f}
• الوقف: {level_price + 8:.2f}
"""
                        try:
                            bot.send_message(chat_id=os.environ.get("TELEGRAM_CHAT_ID"), text=msg, parse_mode="HTML")
                        except Exception as e:
                            logger.error(f"Telegram error: {e}")
                            
                        LAST_ALERTS[level_name] = "Alerted"
            
            # إعادة ضبط التنبيهات عند الابتعاد
            for level_name, level_price in levels.items():
                dist = abs(current_price - level_price)
                if dist > (current_price * 0.002):
                    LAST_ALERTS[level_name] = None
                    
            time.sleep(60)
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(60)
