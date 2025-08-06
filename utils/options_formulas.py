import numpy as np

from option_valuation.binomial_model import BinomialModel
from option_valuation.black_scholes_model import BlackScholesModel
from option_valuation.simple_binomial_model import SimpleBinomialModel
from utils.enums_option import PARAMETERS

"""
Formulas meant to plug into app.components for graphical plots.
Return list of premium pricing: floats for plotting.
"""

def call_blackscholes(
        option_type: str,
        S: np.ndarray,
        params: dict,
    ) -> list:
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
    # Init Model
    option_premiums = []
    for price in S:
        params[PARAMETERS.STOCK_PRICE.value] = price
        SBM = SimpleBinomialModel(option_type, params)
        option_premiums.append(SBM.calculate_price())
    
    return option_premiums