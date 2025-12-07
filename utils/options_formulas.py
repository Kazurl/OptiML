import numpy as np
from scipy.stats import norm

from option_valuation.binomial_model import BinomialModel
from option_valuation.black_scholes_model import BlackScholesModel
from option_valuation.simple_binomial_model import SimpleBinomialModel
from utils.enums_option import PARAMETERS


# === Option Valuation ===
def bs_price(
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "call"
    ) -> float:
    """
    Calculate call or put option price using Black-Scholes model.
    
    Parameters:
        S (float): Underlying stock price
        K (float): Strike/ Exercise price
        T (float): Time to expiry in years
        r (float): Risk free interest rate
        sigma (float): Volatility of stock
        option_type (str): "call" or "put" (default "call")
    
    Returns:
        float: calculated option price
    """
    
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if "call" in option_type.lower() else (K - S))
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if "call" in option_type.lower():
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_greeks(
        S: float,
        K: float, 
        T: float, 
        r: float, 
        sigma: float, 
        option_type: str = "call"
    ) -> dict:  # todo: document on gdoc
    """
    Calculate the Greeks of an option using the Black-Scholes model.

    Parameters:
        S (float): Underlying stock price
        K (float): Strike/ Exercise price
        T (float): Time to expiry in years
        r (float): Risk free interest rate (annualized, decimal)
        sigma (float): Volatility of stock (annualized, decimal)
        option_type (str): "call" or "put" (default "call")

    Returns:
        dict: A dictionary containing the Greeks of the option.
            dict with keys: delta, gamma, vega_per_1pct, theta_per_day, rho_per_1pct
    """
    if T <= 0 or sigma <= 0:
        intrinsic_delta = (
                1.0 if (option_type == "call" and S > K) 
                else (-1.0 if (option_type == "put" and S < K) else 0.0)
            )
        return {
            "delta": intrinsic_delta,
            "gamma": 0.0,
            "vega_per_1pct": 0.0,
            "theta_per_day": 0.0,
            "rho_per_1pct": 0.0
        }
    
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    Nd1, Nd2, nd1 = norm.cdf(d1), norm.cdf(d2), norm.pdf(d1)
    disc = np.exp(-r * T)
    delta = Nd1 if option_type == "call" else (Nd1 - 1.0)
    gamma = nd1 / (S * sigma * sqrtT)
    vega_per_1pct = (S * nd1 * sqrtT) / 100.0
    theta_time = -(S * nd1 * sigma) / (2.0 * sqrtT)
    theta_rate = (-r * K * disc * Nd2) if option_type == "call" else (+r * K * disc * norm.cdf(-d2))
    theta_per_day = (theta_time + theta_rate) / 365.0
    rho_per_1pct = ((K * T * disc * Nd2) if option_type == "call" else (-K * T * disc * norm.cdf(-d2))) / 100.0
    return {
        "delta": delta,
        "gamma": gamma,
        "vega_per_1pct": vega_per_1pct,
        "theta_per_day": theta_per_day,
        "rho_per_1pct": rho_per_1pct
    }


# === Statistics ===
def bs_itm_probability(
        S: float,
        K: float,
        T: float,
        sigma: float,
        option_type: str = "call",
        r: float = 0.0,
        q: float = 0.0
    ) -> float:
    """
    Calculate the probability of an option expiring in-the-money using
    Black-Scholes model by using the cumulative distribution function.
    d1 and d2 are intermediate values used to calculate the probabilities that an
    option will be ITM.
    cdf(d1) represents the expected PV of receiving the asset,
            given that the option is exercised. 
    cdf(d2) represents the probability of the option expiring in-the-money
            i.e. S > K or S < K at expiry.

    Parameters:
        S (float): Underlying stock price
        K (float): Strike/ Exercise price
        T (float): Time to expiry in years
        sigma (float): Volatility of stock
        option_type (str): "call" or "put" (default "call")
        r (float): Risk-free rate (annualized, decimal), default 0.0
        q (float): Dividend yield (annualized, decimal), default 0.0

    Returns:
        float: probability of option expiring in-the-money
    """
    
    if T <= 0 or sigma <= 0:
        return 1.0 if (option_type == "call" and S > K) or (option_type == "put" and S < K) else 0.0
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return norm.cdf(d2) if option_type == "call" else norm.cdf(-d2)


# === Graph Plotting ===
def call_blackscholes(
        option_type: str,
        S: np.ndarray,
        params: dict,
    ) -> list:
    """
    Formulas meant to plug into app.components for graphical plots.

    Parameters:
        option_type (str): utils.enums_option.py's OPTION_TYPE.CALL.value or OPTION_TYPE.PUT.value
        S (np.ndarray): stock_price range
        params (dict): dictionary of option parameters

    Returns:
        list: list of premium pricing floats for plotting.
    """

    # Init Model
    option_premiums = []
    for price in S:
        params[PARAMETERS.STOCK_PRICE.value] = price
        BSM = BlackScholesModel(option_type, params)
        option_premiums.append(BSM.calculate_price())
    
    return option_premiums


def call_binomial(
        option_type: str,
        S: np.ndarray,  # stock_price range
        params: list,
) -> list:
    """
    Formulas meant to plug into app.components for graphical plots.

    Parameters:
        option_type (str): utils.enums_option.py's OPTION_TYPE.CALL.value or OPTION_TYPE.PUT.value
        S (np.ndarray): stock_price range
        params (list): list of option parameters

    Returns:
        list: list of premium pricing floats for plotting.
    """
    
    # Init Model
    option_premiums = []
    for price in S:
        params[PARAMETERS.STOCK_PRICE.value] = price
        BM = BinomialModel(option_type, params)
        option_premiums.append(BM.calculate_price())
    
    return option_premiums


def call_simple_binomial(
        option_type: str,
        S: np.ndarray,  # stock_price range
        params: list,
) -> list:
    """
    Formulas meant to plug into app.components for graphical plots.

    Parameters:
        option_type (str): utils.enums_option.py's OPTION_TYPE.CALL.value or OPTION_TYPE.PUT.value
        S (np.ndarray): stock_price range
        params (list): list of option parameters

    Returns:
        list: list of premium pricing floats for plotting.
    """
    
    # Init Model
    option_premiums = []
    for price in S:
        params[PARAMETERS.STOCK_PRICE.value] = price
        SBM = SimpleBinomialModel(option_type, params)
        option_premiums.append(SBM.calculate_price())
    
    return option_premiums


