import os
from datetime import datetime
import pytz
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BASE_URL = "https://api.alpaca.markets"  # LIVE

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

symbols = [
    "JEPI", "JEPQ", "SCHD", "O", "SGOV",
    "SPY", "QQQ", "VTI", "XYLD", "QYLD"
]

ny = pytz.timezone("America/New_York")

cash_reserve_pct = 0.30
max_position_pct = 0.08
min_order_size = 1.00
max_trades_per_day = 6
max_open_positions = 3

take_profit_pct = 0.006   # +0.6%
stop_loss_pct = -0.004    # -0.4%

force_exit_hour = 15
force_exit_minute = 45


def now_ny():
    return datetime.now(ny)


def is_market_open():
    return api.get_clock().is_open


def get_account():
    account = api.get_account()
    return float(account.cash), float(account.equity)


def get_position(symbol):
    try:
        return api.get_position(symbol)
    except Exception:
        return None


def get_open_positions_count():
    count = 0
    for symbol in symbols:
        if get_position(symbol):
            count += 1
    return count


def todays_trade_count():
    try:
        start = now_ny().replace(hour=0, minute=0, second=0, microsecond=0)
        activities = api.get_activities(
            activity_types="FILL",
            after=start.isoformat()
        )
        return len(activities)
    except Exception as e:
        print("Could not count trades:", e)
        return 0


def get_signal(symbol):
    try:
        bars = api.get_bars(symbol, TimeFrame.Minute, limit=30).df

        if len(bars) < 20:
            return "hold"

        close = bars["close"]
        last = close.iloc[-1]
        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()

        previous = close.iloc[-2]
        change_pct = (last - previous) / previous

        if last > ma5 > ma20 and change_pct > 0:
            return "buy"

        return "hold"

    except Exception as e:
        print(f"Signal failed for {symbol}: {e}")
        return "hold"


def submit_buy(symbol, amount):
    if amount < min_order_size:
        return False

    print(f"BUY {symbol} ${round(amount, 2)}")

    try:
        api.submit_order(
            symbol=symbol,
            notional=round(amount, 2),
            side="buy",
            type="market",
            time_in_force="day"
        )
        return True
    except Exception as e:
        print(f"Buy failed for {symbol}: {e}")
        return False


def submit_sell(symbol, qty):
    if qty <= 0:
        return False

    print(f"SELL {symbol} qty {qty}")

    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day"
        )
        return True
    except Exception as e:
        print(f"Sell failed for {symbol}: {e}")
        return False


def manage_positions():
    current_time = now_ny()

    force_exit = (
        current_time.hour > force_exit_hour or
        (current_time.hour == force_exit_hour and current_time.minute >= force_exit_minute)
    )

    for symbol in symbols:
        position = get_position(symbol)

        if not position:
            continue

        qty = float(position.qty)
        avg_entry = float(position.avg_entry_price)
        current_price = float(position.current_price)

        if avg_entry <= 0:
            continue

        gain_pct = (current_price - avg_entry) / avg_entry

        if gain_pct >= take_profit_pct:
            print(f"{symbol} profit target hit: {round(gain_pct * 100, 2)}%")
            submit_sell(symbol, qty)

        elif gain_pct <= stop_loss_pct:
            print(f"{symbol} stop loss hit: {round(gain_pct * 100, 2)}%")
            submit_sell(symbol, qty)

        elif force_exit:
            print(f"{symbol} force exit before close")
            submit_sell(symbol, qty)


def open_new_trades():
    trades_today = todays_trade_count()

    if trades_today >= max_trades_per_day:
        print("Max daily trades reached.")
        return

    if get_open_positions_count() >= max_open_positions:
        print("Max open positions reached.")
        return

    cash, equity = get_account()
    reserve_cash = equity * cash_reserve_pct
    investable_cash = cash - reserve_cash

    if investable_cash < min_order_size:
        print("Not enough investable cash.")
        return

    for symbol in symbols:
        if todays_trade_count() >= max_trades_per_day:
            break

        if get_open_positions_count() >= max_open_positions:
            break

        if get_position(symbol):
            continue

        signal = get_signal(symbol)
        print(f"{symbol} signal: {signal}")

        if signal == "buy":
            amount = equity * max_position_pct
            amount = min(amount, investable_cash)

            submit_buy(symbol, amount)


def run_bot():
    print("----- STOCK DAY TRADING BOT START -----")

    if not is_market_open():
        print("Market closed. No trades.")
        return

    print(f"Time NY: {now_ny()}")

    manage_positions()
    open_new_trades()

    print("----- STOCK DAY TRADING BOT END -----")


if __name__ == "__main__":
    run_bot()
