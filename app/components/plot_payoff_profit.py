from typing import Tuple
import numpy as np
import matplotlib.pyplot as plt

def show_plot_payoff_profit(
        option_type: str,
        strike_price: float,
        option_premium: float,
        stock_price_range: Tuple[float, float, int]
    ):
    X = strike_price     # Strike price
    CP = option_premium     # Option premium (cost)
    # Possible prices at expiry
    S = np.linspace(stock_price_range[0], stock_price_range[1], stock_price_range[2])

    payoff = np.maximum(S - CP, 0)       # Call payoff at expiry
    profit = payoff - CP                 # Net profit at expiry

    fig, ax = plt.subplots(figsize=(8,5))
    ax.plot(S, profit, label='Profit', color='dodgerblue')
    ax.axhline(0, color='black', lw=1)
    ax.axvline(X+CP, color='grey', ls='--', label='Breakeven')
    ax.set_title(f'{option_type.split(" ")[0].capitalize()} Payoff at Expiration')
    ax.set_xlabel('Underlying Price $S_T$')
    ax.set_ylabel('Profit')
    ax.legend()
    ax.grid(True)
    return fig