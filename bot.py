import os
import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import TimeFrame

API_KEY = os.getenv("API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BASE_URL = "https://api.alpaca.markets"

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version="v2")

# 🔥 Updated allocation (DOGE added)
targets = {
    "JEPI": 0.18,
    "JEPQ": 0.12,
    "XYLD": 0.08,
    "QYLD": 0.07,
    "O": 0.10,
    "SCHD": 0.15,
    "SGOV": 0.15,
    "VTI": 0.10,
    "BTC/USD": 0.02,
    "ETH/USD": 0.02,
    "DOGE/USD": 0.01
}

# 🔥 Crypto list updated
crypto_assets = ["BTC/USD", "ETH/USD", "DOGE/USD"]

cash_reserve_pct = 0.10
min_order_size = 1.00
max_single_asset_pct = 0.25
max_crypto_total_pct = 0.05

max_trades_per_run = 8

# 🔥 Faster trading
profit_level_1 = 0.02
profit_level_2 = 0.04
profit_level_3 = 0.08

stop_loss_pct = -0.08
crash_protection_pct = -0.04


def is_market_open():
    return api.get_clock().is_open


def normalize_symbol(symbol):
    if symbol == "BTCUSD":
        return "BTC/USD"
    if symbol == "ETHUSD":
        return "ETH/USD"
    if symbol == "DOGEUSD":
        return "DOGE/USD"
    return symbol


def order_time_in_force(symbol):
    return "gtc" if symbol in crypto_assets else "day"


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
    return sum(portfolio.get(asset, 0) for asset in crypto_assets) / total_value


def get_market_condition():
    try:
        bars = api.get_bars("VTI", TimeFrame.Day, limit=10).df

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

    print(f"EXECUTED BUY: {symbol} ${round(dollar_amount, 2)}")

    try:
        api.submit_order(
            symbol=symbol,
            notional=round(dollar_amount, 2),
            side="buy",
            type="market",
            time_in_force=order_time_in_force(symbol)
        )
        return True
    except Exception as e:
        print(f"Buy failed for {symbol}: {e}")
        return False


def submit_sell(symbol, qty):
    if qty <= 0:
        return False

    print(f"EXECUTED SELL: {symbol} qty {qty}")

    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force=order_time_in_force(symbol)
        )
        return True
    except Exception as e:
        print(f"Sell failed for {symbol}: {e}")
        return False


def check_profit_take_and_stop_loss(positions, market_open):
    trades = 0

    for p in positions:
        if trades >= max_trades_per_run:
            break

        symbol = normalize_symbol(p.symbol)

        if symbol not in crypto_assets and not market_open:
            continue

        avg_entry_price = float(p.avg_entry_price)
        current_price = float(p.current_price)
        qty = float(p.qty)

        if avg_entry_price <= 0:
            continue

        gain_pct = (current_price - avg_entry_price) / avg_entry_price

        # 🔥 Crypto trades faster (DOGE included)
        if symbol in crypto_assets:
            local_p1 = 0.015
            local_p2 = 0.03
            local_p3 = 0.06
        else:
            local_p1 = profit_level_1
            local_p2 = profit_level_2
            local_p3 = profit_level_3

        # Stop loss
        if gain_pct <= stop_loss_pct:
            qty_to_sell = qty * 0.50
            print(f"{symbol} STOP LOSS {round(gain_pct * 100, 2)}%")

            if submit_sell(symbol, qty_to_sell):
                trades += 1
            continue

        # Profit taking
        if gain_pct >= local_p3:
            sell_pct = 0.60
        elif gain_pct >= local_p2:
            sell_pct = 0.40
        elif gain_pct >= local_p1:
            sell_pct = 0.20
        else:
            continue

        qty_to_sell = qty * sell_pct

        print(f"{symbol} PROFIT {round(gain_pct * 100, 2)}%")

        if submit_sell(symbol, qty_to_sell):
            trades += 1


def buy_underweight_assets():
    portfolio, total_value, cash, positions = get_portfolio()

    required_cash_reserve = total_value * cash_reserve_pct
    investable_cash = cash - required_cash_reserve

    if investable_cash < min_order_size:
        print("Not enough cash.")
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
        print("Nothing to buy.")
        return

    total_gap = sum(gap for _, gap in underweight_assets)
    trades = 0

    for symbol, gap in underweight_assets:
        if trades >= max_trades_per_run:
            break

        buy_amount = investable_cash * (gap / total_gap)

        if submit_buy(symbol, buy_amount):
            trades += 1


def buy_crypto_only():
    portfolio, total_value, cash, positions = get_portfolio()

    investable_cash = cash - (total_value * cash_reserve_pct)

    if investable_cash < min_order_size:
        return

    for symbol in crypto_assets:
        buy_amount = investable_cash / len(crypto_assets)
        submit_buy(symbol, buy_amount)


def run_bot():
    print("----- BOT RUN START -----")

    portfolio, total_value, cash, positions = get_portfolio()
    market_open = is_market_open()

    print(f"Portfolio: ${round(total_value, 2)} | Cash: ${round(cash, 2)}")

    check_profit_take_and_stop_loss(positions, market_open)

    if market_open:
        buy_underweight_assets()
    else:
        buy_crypto_only()

    print("----- BOT RUN END -----")


if __name__ == "__main__":
    run_bot()
