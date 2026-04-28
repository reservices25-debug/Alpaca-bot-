import os
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BASE_URL = "https://api.alpaca.markets"  # LIVE

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

targets = {
    "SGOV": 0.20,
    "VTI": 0.20,
    "SCHD": 0.20,
    "JEPI": 0.20,
    "O": 0.15,
    "BTC/USD": 0.025,
    "ETH/USD": 0.025
}

crypto_assets = ["BTC/USD", "ETH/USD"]

cash_reserve_pct = 0.10
min_order_size = 1.00
max_single_asset_pct = 0.30
max_crypto_total_pct = 0.05

max_trades_per_run = 5

profit_level_1 = 0.05
profit_level_2 = 0.10
profit_level_3 = 0.20

stop_loss_pct = -0.08
crash_protection_pct = -0.04


def is_market_open():
    clock = api.get_clock()
    return clock.is_open


def normalize_symbol(symbol):
    if symbol == "BTCUSD":
        return "BTC/USD"
    if symbol == "ETHUSD":
        return "ETH/USD"
    return symbol


def order_time_in_force(symbol):
    if symbol in crypto_assets:
        return "gtc"
    return "day"


def get_portfolio():
    positions = api.list_positions()
    portfolio = {}
    total_positions_value = 0

    for p in positions:
        symbol = normalize_symbol(p.symbol)
        value = float(p.market_value)
        portfolio[symbol] = value
        total_positions_value += value

    account = api.get_account()
    cash = float(account.cash)
    total_value = total_positions_value + cash

    return portfolio, total_value, cash, positions


def get_current_allocation(portfolio, total_value, symbol):
    if total_value <= 0:
        return 0
    return portfolio.get(symbol, 0) / total_value


def get_crypto_allocation(portfolio, total_value):
    if total_value <= 0:
        return 0
    crypto_value = sum(portfolio.get(asset, 0) for asset in crypto_assets)
    return crypto_value / total_value


def get_market_condition():
    try:
        bars = api.get_bars("VTI", TimeFrame.Day, limit=3).df

        if len(bars) < 2:
            return "neutral"

        latest = bars.iloc[-1]
        previous = bars.iloc[-2]

        change_pct = (latest["close"] - previous["close"]) / previous["close"]

        if change_pct <= crash_protection_pct:
            return "crash"
        elif change_pct <= -0.02:
            return "dip"
        elif change_pct >= 0.02:
            return "strong"
        else:
            return "neutral"

    except Exception as e:
        print("Market check failed:", e)
        return "neutral"


def submit_buy(symbol, dollar_amount):
    if dollar_amount < min_order_size:
        return False

    print(f"Buying ${round(dollar_amount, 2)} of {symbol}")

    api.submit_order(
        symbol=symbol,
        notional=round(dollar_amount, 2),
        side="buy",
        type="market",
        time_in_force=order_time_in_force(symbol)
    )

    return True


def submit_sell(symbol, qty):
    if qty <= 0:
        return False

    print(f"Selling {qty} of {symbol}")

    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="sell",
        type="market",
        time_in_force=order_time_in_force(symbol)
    )

    return True


def check_profit_take_and_stop_loss(positions):
    trades = 0

    for p in positions:
        if trades >= max_trades_per_run:
            break

        symbol = normalize_symbol(p.symbol)

        if symbol in crypto_assets:
            continue

        avg_entry_price = float(p.avg_entry_price)
        current_price = float(p.current_price)
        qty = float(p.qty)

        if avg_entry_price <= 0:
            continue

        gain_pct = (current_price - avg_entry_price) / avg_entry_price

        # Stop-loss protection
        if gain_pct <= stop_loss_pct:
            qty_to_sell = qty * 0.50
            print(f"{symbol} down {round(gain_pct * 100, 2)}% → defensive sell 50%")
            if submit_sell(symbol, qty_to_sell):
                trades += 1
            continue

        # Multi-level profit taking
        if gain_pct >= profit_level_3:
            sell_pct = 0.60
        elif gain_pct >= profit_level_2:
            sell_pct = 0.40
        elif gain_pct >= profit_level_1:
            sell_pct = 0.20
        else:
            continue

        qty_to_sell = qty * sell_pct

        print(
            f"{symbol} up {round(gain_pct * 100, 2)}% "
            f"→ taking profit on {int(sell_pct * 100)}%"
        )

        if submit_sell(symbol, qty_to_sell):
            trades += 1


def buy_underweight_assets():
    portfolio, total_value, cash, positions = get_portfolio()

    required_cash_reserve = total_value * cash_reserve_pct
    investable_cash = cash - required_cash_reserve

    if investable_cash < min_order_size:
        print("Not enough investable cash.")
        return

    market_condition = get_market_condition()
    print("Market condition:", market_condition)

    crypto_allocation = get_crypto_allocation(portfolio, total_value)
    underweight_assets = []

    for symbol, target_pct in targets.items():
        current_pct = get_current_allocation(portfolio, total_value, symbol)

        if current_pct >= target_pct:
            continue

        if current_pct >= max_single_asset_pct:
            continue

        if symbol in crypto_assets and crypto_allocation >= max_crypto_total_pct:
            continue

        # Elite behavior
        if market_condition == "crash":
            # In crash mode, protect capital with SGOV only
            if symbol != "SGOV":
                continue

        elif market_condition == "dip":
            # In normal dip, buy growth/dividend strength
            if symbol not in ["VTI", "SCHD", "SGOV"]:
                continue

        elif market_condition == "strong":
            # In hot market, avoid chasing VTI
            if symbol == "VTI":
                continue

        gap = target_pct - current_pct
        underweight_assets.append((symbol, gap))

    if not underweight_assets:
        print("No underweight assets to buy.")
        return

    total_gap = sum(gap for _, gap in underweight_assets)
    trades = 0

    for symbol, gap in underweight_assets:
        if trades >= max_trades_per_run:
            break

        buy_amount = investable_cash * (gap / total_gap)

        if submit_buy(symbol, buy_amount):
            trades += 1


def run_bot():
    portfolio, total_value, cash, positions = get_portfolio()

    print(f"Total portfolio value: ${round(total_value, 2)}")
    print(f"Cash available: ${round(cash, 2)}")

    # Stocks only run during market hours
    if not is_market_open():
        print("Stock market is closed. Bot will not place stock trades now.")
        return

    check_profit_take_and_stop_loss(positions)
    buy_underweight_assets()

    print("Elite live bot run complete.")


if __name__ == "__main__":
    run_bot()
