import os
import alpaca_trade_api as tradeapi

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BASE_URL = "https://api.alpaca.markets"  # LIVE trading

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


def get_portfolio():
    positions = api.list_positions()
    portfolio = {}
    total_positions_value = 0

    for p in positions:
        symbol = p.symbol
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
        bars = api.get_bars("VTI", "1Day", limit=2).df

        if len(bars) < 2:
            return "neutral"

        latest = bars.iloc[-1]
        previous = bars.iloc[-2]

        change_pct = (latest["close"] - previous["close"]) / previous["close"]

        if change_pct <= -0.02:
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
        return

    print(f"Buying ${round(dollar_amount, 2)} of {symbol}")

    api.submit_order(
        symbol=symbol,
        notional=round(dollar_amount, 2),
        side="buy",
        type="market",
        time_in_force="day"
    )


def submit_sell(symbol, qty):
    if qty <= 0:
        return

    print(f"Selling {qty} of {symbol} to take profit")

    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="sell",
        type="market",
        time_in_force="day"
    )


def check_profit_take(positions):
    for p in positions:
        symbol = p.symbol

        if symbol in crypto_assets:
            continue

        avg_entry_price = float(p.avg_entry_price)
        current_price = float(p.current_price)
        qty = float(p.qty)

        if avg_entry_price <= 0:
            continue

        gain_pct = (current_price - avg_entry_price) / avg_entry_price

        if gain_pct >= 0.10:
            sell_pct = 0.50
        elif gain_pct >= 0.05:
            sell_pct = 0.25
        else:
            continue

        qty_to_sell = qty * sell_pct

        print(
            f"{symbol} up {round(gain_pct * 100, 2)}% "
            f"→ Selling {int(sell_pct * 100)}%"
        )

        submit_sell(symbol, qty_to_sell)


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

        # Smart market behavior
        if market_condition == "dip":
            # During dips, only buy core growth/dividend growth
            if symbol not in ["VTI", "SCHD"]:
                continue

        elif market_condition == "strong":
            # During strong market moves, pause VTI and focus income/safety
            if symbol == "VTI":
                continue

        gap = target_pct - current_pct
        underweight_assets.append((symbol, gap))

    if not underweight_assets:
        print("No underweight assets to buy.")
        return

    total_gap = sum(gap for _, gap in underweight_assets)

    for symbol, gap in underweight_assets:
        buy_amount = investable_cash * (gap / total_gap)
        submit_buy(symbol, buy_amount)


def run_bot():
    portfolio, total_value, cash, positions = get_portfolio()

    print(f"Total portfolio value: ${round(total_value, 2)}")
    print(f"Cash available: ${round(cash, 2)}")

    check_profit_take(positions)
    buy_underweight_assets()

    print("Live smart bot run complete.")


if __name__ == "__main__":
    run_bot()
