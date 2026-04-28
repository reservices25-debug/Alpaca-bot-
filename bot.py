import os
import alpaca_trade_api as tradeapi

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BASE_URL = "https://paper-api.alpaca.markets"  # paper testing first
# BASE_URL = "https://api.alpaca.markets"      # live later

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

targets = {
    "SGOV": 0.25,      # safety
    "VTI": 0.25,       # growth
    "SCHD": 0.20,      # dividend growth
    "JEPI": 0.15,      # income
    "O": 0.10,         # REIT income
    "BTC/USD": 0.025,  # crypto growth
    "ETH/USD": 0.025   # crypto growth
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

    return portfolio, total_value, cash


def get_current_allocation(portfolio, total_value, symbol):
    if total_value <= 0:
        return 0
    return portfolio.get(symbol, 0) / total_value


def get_crypto_allocation(portfolio, total_value):
    if total_value <= 0:
        return 0

    crypto_value = sum(portfolio.get(asset, 0) for asset in crypto_assets)
    return crypto_value / total_value


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


def run_bot():
    portfolio, total_value, cash = get_portfolio()

    required_cash_reserve = total_value * cash_reserve_pct
    investable_cash = cash - required_cash_reserve

    if investable_cash < min_order_size:
        print("Not enough investable cash.")
        return

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

        gap = target_pct - current_pct
        underweight_assets.append((symbol, gap))

    if not underweight_assets:
        print("No underweight assets to buy.")
        return

    total_gap = sum(gap for _, gap in underweight_assets)

    for symbol, gap in underweight_assets:
        buy_amount = investable_cash * (gap / total_gap)
        submit_buy(symbol, buy_amount)


if __name__ == "__main__":
    run_bot()
