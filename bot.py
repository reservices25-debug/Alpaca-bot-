import os
import csv
from pathlib import Path
from datetime import datetime
import pytz
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

# =====================
# API SETUP
# =====================

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

# =====================
# SYMBOL UNIVERSE
# =====================

symbols = [
    "SPY","QQQ","VTI","VOO","DIA","IWM",
    "JEPI","JEPQ","SCHD","VYM","SPHD","XYLD","QYLD",
    "SGOV","BIL","SHV",
    "O","STAG","MAIN",
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
    "JPM","BAC","V","MA",
    "KO","PEP","PG","JNJ","WMT","T",
    "XOM","CVX",
    "XLK","XLF","XLE","XLV","XLP","XLY"
]

ny = pytz.timezone("America/New_York")

# =====================
# SETTINGS
# =====================

cash_reserve_pct = 0.30
base_position_pct = 0.06
min_position_pct = 0.03
max_position_pct = 0.08
min_order_size = 1.00

max_trades_per_day = 10
max_open_positions = 4

take_profit_pct = 0.018
minimum_profit_lock_pct = 0.006
stop_loss_pct = -0.005
daily_loss_limit_pct = -0.02

min_entry_score = 4
min_hold_score = 2
volatility_limit = 0.035

# =====================
# HELPERS
# =====================

def now_ny():
    return datetime.now(ny)

def log(msg):
    print(f"[{now_ny()}] {msg}")

def get_account():
    acc = api.get_account()
    return float(acc.cash), float(acc.equity), float(acc.last_equity)

def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None

def get_session():
    t = now_ny().time()
    if t < datetime.strptime("09:30","%H:%M").time():
        return "pre"
    if t <= datetime.strptime("16:00","%H:%M").time():
        return "regular"
    return "after"

# =====================
# MARKET LOGIC
# =====================

def market_regime():
    bars = api.get_bars("SPY", TimeFrame.Day, limit=60).df
    close = bars["close"]
    price = close.iloc[-1]
    ma20 = close.tail(20).mean()
    ma50 = close.tail(50).mean()

    if price > ma20 > ma50:
        return "bullish"
    if price < ma20 < ma50:
        return "bearish"
    return "neutral"

def score(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=60).df
        close = bars["close"]

        last = close.iloc[-1]
        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()

        s = 0
        if last > ma5: s += 1
        if ma5 > ma20: s += 1
        if last > ma20: s += 1

        return s
    except:
        return -999

def rank_symbols():
    ranked = [(s, score(s)) for s in symbols]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked

# =====================
# TRADING
# =====================

def submit_buy(symbol, amount):
    if amount < min_order_size:
        return False

    api.submit_order(
        symbol=symbol,
        notional=round(amount,2),
        side="buy",
        type="market",
        time_in_force="day"
    )
    log(f"BUY {symbol} ${round(amount,2)}")
    return True

def submit_sell(symbol, qty, reason):
    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="sell",
        type="market",
        time_in_force="day"
    )
    log(f"SELL {symbol} {reason}")

# =====================
# CORE ENGINE
# =====================

def manage_positions():
    ranked = rank_symbols()
    top_symbols = [s for s, sc in ranked[:max_open_positions]]

    for symbol in symbols:
        pos = get_position(symbol)
        if not pos:
            continue

        qty = float(pos.qty)
        entry = float(pos.avg_entry_price)
        price = float(pos.current_price)

        gain = (price - entry) / entry
        sc = score(symbol)

        # PROFIT
        if gain >= take_profit_pct:
            submit_sell(symbol, qty, "TAKE PROFIT")
            continue

        # LOCK SMALL WIN
        if gain >= minimum_profit_lock_pct and sc < min_hold_score:
            submit_sell(symbol, qty, "LOCK PROFIT")
            continue

        # STOP LOSS
        if gain <= stop_loss_pct:
            submit_sell(symbol, qty, "STOP LOSS")
            continue

        # ROTATE LOSERS ONLY
        if gain < 0 and symbol not in top_symbols:
            submit_sell(symbol, qty, "ROTATION")
            continue

# =====================
# ENTRY ENGINE
# =====================

def open_trades():
    cash, equity, last_equity = get_account()

    ranked = rank_symbols()
    open_positions = [s for s in symbols if get_position(s)]

    slots = max_open_positions - len(open_positions)
    if slots <= 0:
        return

    reserve = equity * cash_reserve_pct
    investable = cash - reserve

    for symbol, sc in ranked:
        if slots <= 0:
            break
        if sc < min_entry_score:
            continue
        if get_position(symbol):
            continue

        amount = min(equity * base_position_pct, investable)

        if submit_buy(symbol, amount):
            investable -= amount
            slots -= 1

# =====================
# MAIN LOOP
# =====================

def run_bot():
    log("START BOT")

    manage_positions()
    open_trades()

    log("END BOT")

if __name__ == "__main__":
    run_bot()
