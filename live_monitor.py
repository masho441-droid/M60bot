import logging, time, requests, os
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

# ===== حالة البوت =====
ACTIVE_TRADE = None
LAST_ALERT = 0
TRADES_TODAY = 0
LOSSES_IN_ROW = 0
LAST_TRADE_CLOSE_TIME = 0

def get_spx_1m():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, params={"range": "1d", "interval": "1m"}, timeout=10)
        data = r.json()
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({
            "time": pd.to_datetime(ts, unit="s"),
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"]
        })
        return df.dropna()
    except Exception as e:
        logger.error(f"Data error: {e}")
        return None

def send_alert(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def monitor_market_dynamic():
    global ACTIVE_TRADE, LAST_ALERT, TRADES_TODAY, LOSSES_IN_ROW, LAST_TRADE_CLOSE_TIME
    logger.info("VWAP + ORB + EMA9 + Volume - Strong Strategy Started")
    send_alert("✅ <b>البوت اشتغل - استراتيجية قوية</b>\nVWAP + افتتاح 15 د + EMA 9 + فوليوم\nعقد واحد | حد أقصى 10 صفقات | يوقف بعد 3 خساير ورا بعض")

    while True:
        try:
            df = get_spx_1m()
            if df is None or len(df) < 30:
                time.sleep(60)
                continue

            price = float(df['close'].iloc[-1])
            now_str = datetime.now().strftime("%H:%M:%S")

            # ===== VWAP =====
            df['tp'] = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
            vwap = float(df['vwap'].iloc[-1])

            # ===== EMA 9 =====
            df['ema9'] = df['close'].ewm(span=9).mean()
            ema9 = float(df['ema9'].iloc[-1])

            # ===== فوليوم =====
            avg_vol = float(df['volume'].tail(20
