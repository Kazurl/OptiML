from typing import Tuple
import matplotlib.pyplot as plt
import numpy as np

from utils.enums_option import OPTION_MODEL, PARAMETERS
from utils.options_formulas import call_binomial, call_blackscholes, call_simple_binomial

def show_plot_premium_price(
        option_type: str,
        option_model: str,
        S: Tuple[float, float, int],  # stock_price range
        X: float,  # strike_price
        T: int,  # days_to_maturity
        r: float,  # interest_rate
        sigma: float,  # volatility
        q: float = 0,  # dividend
        N: int = 100,  # int
    ):
    # Standardize params
    S = np.linspace(*S)
    params = {
        PARAMETERS.STRIKE_PRICE.value: X,
        PARAMETERS.DAYS_TO_EXPIRY.value: T,
        PARAMETERS.INTEREST_RATE.value: r,
        PARAMETERS.VOLATILITY.value: sigma,
        PARAMETERS.DIVIDEND_YIELD.value: q,
        PARAMETERS.TIME_STEPS.value: N
    }

    # Calculate array of premiums
    if option_model == OPTION_MODEL.BLACK_SCHOLES_MODEL.value:
        option_premiums = call_blackscholes(option_type, S, params)
    elif option_model == OPTION_MODEL.BINOMIAL_MODEL.value:
        option_premiums = call_binomial(option_type, S, params)
    else:
        option_premiums = call_simple_binomial(option_type, S, params)
    
    # Plot relevant graph
    if option_type == "call option":
        title = "Call Option Value vs Underlying Price"
    else:
        title = "Put Option Value vs Underlying Price"

    fig, ax = plt.subplots(figsize=(8,5))
    ax.plot(S, option_premiums, label=f"Option Value ({option_model})", color='purple')
    ax.set_title(title)
    ax.set_xlabel('Underlying Price $S$')
    ax.set_ylabel('Option Value')
    ax.legend()
    ax.grid(True)
    return fig