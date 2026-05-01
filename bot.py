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
BASE_URL = "https://api.alpaca.markets"  # LIVE trading

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

# =====================
# SYMBOL UNIVERSE
# =====================

symbols = [
    "SPY", "QQQ", "VTI", "VOO", "DIA", "IWM",
    "JEPI", "JEPQ", "SCHD", "VYM", "SPHD", "XYLD", "QYLD",
    "SGOV", "BIL", "SHV",
    "O", "STAG", "MAIN",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    "JPM", "BAC", "V", "MA",
    "KO", "PEP", "PG", "JNJ", "WMT", "T",
    "XOM", "CVX",
    "XLK", "XLF", "XLE", "XLV", "XLP", "XLY"
]

ny = pytz.timezone("America/New_York")

# =====================
# SETTINGS - HIGH ACTIVITY MODE
# =====================

cash_reserve_pct = 0.10
base_position_pct = 0.05
min_position_pct = 0.02
max_position_pct = 0.08
min_order_size = 1.00

max_trades_per_day = 20
max_open_positions = 8

take_profit_pct = 0.012
minimum_profit_lock_pct = 0.004
stop_loss_pct = -0.006
daily_loss_limit_pct = -0.025

min_entry_score = 2
min_hold_score = 2
volatility_limit = 0.05

TRADE_LOG = "trade_log.csv"
SNAPSHOT_LOG = "portfolio_snapshot.csv"
RISK_REPORT = "risk_report.txt"
PERFORMANCE_REPORT = "performance_report.txt"

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
    except Exception:
        return None

def get_session():
    t = now_ny().time()

    if t < datetime.strptime("09:30", "%H:%M").time():
        return "pre"
    if t <= datetime.strptime("16:00", "%H:%M").time():
        return "regular"
    return "after"

def market_is_open():
    try:
        clock = api.get_clock()
        return clock.is_open
    except Exception as e:
        log(f"CLOCK ERROR: {e}")
        return False

# =====================
# LOGGING
# =====================

def write_trade_log(symbol, side, reason, amount_or_qty):
    file_exists = Path(TRADE_LOG).exists()

    with open(TRADE_LOG, "a", newline="") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["time", "symbol", "side", "reason", "amount_or_qty"])

        writer.writerow([now_ny(), symbol, side, reason, amount_or_qty])

def write_snapshot():
    try:
        cash, equity, last_equity = get_account()
        file_exists = Path(SNAPSHOT_LOG).exists()

        with open(SNAPSHOT_LOG, "a", newline="") as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow(["time", "cash", "equity", "last_equity"])

            writer.writerow([now_ny(), cash, equity, last_equity])

    except Exception as e:
        log(f"SNAPSHOT ERROR: {e}")

def write_reports():
    try:
        cash, equity, last_equity = get_account()
        daily_change = (equity - last_equity) / last_equity if last_equity > 0 else 0

        with open(RISK_REPORT, "w") as f:
            f.write("RISK REPORT\n")
            f.write("====================\n")
            f.write(f"Time: {now_ny()}\n")
            f.write(f"Cash: {cash}\n")
            f.write(f"Equity: {equity}\n")
            f.write(f"Last Equity: {last_equity}\n")
            f.write(f"Daily Change: {daily_change:.4f}\n")
            f.write(f"Daily Loss Limit: {daily_loss_limit_pct}\n")

        with open(PERFORMANCE_REPORT, "w") as f:
            f.write("PERFORMANCE REPORT\n")
            f.write("====================\n")
            f.write(f"Time: {now_ny()}\n")
            f.write(f"Cash: {cash}\n")
            f.write(f"Equity: {equity}\n")
            f.write(f"Open Positions: {len(api.list_positions())}\n")

    except Exception as e:
        log(f"REPORT ERROR: {e}")

# =====================
# MARKET LOGIC
# =====================

def market_regime():
    try:
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

    except Exception as e:
        log(f"REGIME ERROR: {e}")
        return "neutral"

def volatility_ok(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=30).df
        close = bars["close"]

        high = close.max()
        low = close.min()
        last = close.iloc[-1]

        vol = (high - low) / last

        return vol <= volatility_limit

    except Exception:
        return False

def score(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=30).df
        close = bars["close"]

        if len(close) < 20:
            return -999

        last = close.iloc[-1]
        ma3 = close.tail(3).mean()
        ma8 = close.tail(8).mean()
        ma20 = close.tail(20).mean()

        s = 0

        if last > ma3:
            s += 1

        if ma3 > ma8:
            s += 1

        if last > ma20:
            s += 1

        if close.iloc[-1] > close.iloc[-2]:
            s += 1

        if not volatility_ok(symbol):
            s -= 1

        return s

    except Exception as e:
        log(f"SCORE ERROR {symbol}: {e}")
        return -999

def rank_symbols():
    ranked = [(s, score(s)) for s in symbols]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked

# =====================
# TRADING
# =====================

def submit_buy(symbol, amount):
    try:
        if amount < min_order_size:
            return False

        api.submit_order(
            symbol=symbol,
            notional=round(amount, 2),
            side="buy",
            type="market",
            time_in_force="day"
        )

        log(f"BUY {symbol} ${round(amount, 2)}")
        write_trade_log(symbol, "BUY", "ENTRY", round(amount, 2))
        return True

    except Exception as e:
        log(f"BUY ERROR {symbol}: {e}")
        return False

def submit_sell(symbol, qty, reason):
    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day"
        )

        log(f"SELL {symbol} {reason}")
        write_trade_log(symbol, "SELL", reason, qty)
        return True

    except Exception as e:
        log(f"SELL ERROR {symbol}: {e}")
        return False

# =====================
# CORE ENGINE
# =====================

def daily_risk_ok():
    try:
        cash, equity, last_equity = get_account()

        if last_equity <= 0:
            return True

        daily_change = (equity - last_equity) / last_equity

        if daily_change <= daily_loss_limit_pct:
            log("DAILY LOSS LIMIT HIT - BOT PAUSED")
            return False

        return True

    except Exception as e:
        log(f"DAILY RISK ERROR: {e}")
        return False

def manage_positions():
    ranked = rank_symbols()
    top_symbols = [s for s, sc in ranked[:max_open_positions]]

    for symbol in symbols:
        pos = get_position(symbol)

        if not pos:
            continue

        try:
            qty = float(pos.qty)
            entry = float(pos.avg_entry_price)
            price = float(pos.current_price)

            if entry <= 0:
                continue

            gain = (price - entry) / entry
            sc = score(symbol)

            if gain >= take_profit_pct:
                submit_sell(symbol, qty, "TAKE PROFIT")
                continue

            if gain >= minimum_profit_lock_pct and sc < min_hold_score:
                submit_sell(symbol, qty, "LOCK SMALL WIN")
                continue

            if gain <= stop_loss_pct:
                submit_sell(symbol, qty, "STOP LOSS")
                continue

            if gain < 0 and symbol not in top_symbols:
                submit_sell(symbol, qty, "ROTATION OUT")
                continue

        except Exception as e:
            log(f"MANAGE ERROR {symbol}: {e}")

def open_trades():
    if not daily_risk_ok():
        return

    session = get_session()

    if session != "regular":
        log("OUTSIDE REGULAR MARKET HOURS - SKIPPING BUYS")
        return

    cash, equity, last_equity = get_account()

    reserve = equity * cash_reserve_pct
    investable = cash - reserve

    if investable < min_order_size:
        log("NOT ENOUGH INVESTABLE CASH")
        return

    ranked = rank_symbols()

    open_positions = [s for s in symbols if get_position(s)]
    slots = max_open_positions - len(open_positions)

    if slots <= 0:
        log("MAX OPEN POSITIONS REACHED")
        return

    trades_opened = 0

    regime = market_regime()

    for symbol, sc in ranked:
        if trades_opened >= max_trades_per_day:
            break

        if slots <= 0:
            break

        if sc < min_entry_score:
            continue

        if get_position(symbol):
            continue

        if regime == "bearish" and symbol not in ["SGOV", "BIL", "SHV"]:
            continue

        amount = min(
            equity * base_position_pct,
            investable,
            equity * max_position_pct
        )

        if amount < min_order_size:
            continue

        if submit_buy(symbol, amount):
            investable -= amount
            slots -= 1
            trades_opened += 1

    if trades_opened == 0:
        log("NO ENTRY SIGNALS FOUND")

# =====================
# MAIN LOOP
# =====================

def run_bot():
    log("START BOT")

    if not market_is_open():
        log("MARKET CLOSED")
        write_snapshot()
        write_reports()
        log("END BOT")
        return

    manage_positions()
    open_trades()
    write_snapshot()
    write_reports()

    log("END BOT")

if __name__ == "__main__":
    run_bot()
