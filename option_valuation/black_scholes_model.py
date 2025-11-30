import numpy as np
from scipy.stats import norm

from .base_option import OptionValuationModel
from utils.enums_option import OPTION_TYPE, PARAMETERS

class BlackScholesModel(OptionValuationModel):
    def __init__(
            self,
            option_type: OPTION_TYPE,
            parameters: dict,
            dividend_yield: float = 0.0
        ) -> None:
        """
            Initialize parameters used to calculate call and put prices.
            Parameters:
                1. stock_price - Underlying stock price
                2. strike_price - Strike/ Exercise price
                3. days_to_expiry - Days to expiry
                4. interest_rate - Risk free interest rate
                5. volatility - Volatility of stock
                6. dividend_yeild - Stock dividend yield 
        """
        super().__init__(option_type, parameters)
        self.S = self.parameters[PARAMETERS.STOCK_PRICE.value]
        self.K = self.parameters[PARAMETERS.STRIKE_PRICE.value]
        self.T = self.parameters[PARAMETERS.DAYS_TO_EXPIRY.value] / 365
        self.r = self.parameters[PARAMETERS.INTEREST_RATE.value]
        self.sigma = self.parameters[PARAMETERS.VOLATILITY.value]
        if PARAMETERS.DIVIDEND_YIELD.value in self.parameters and self.parameters[PARAMETERS.DIVIDEND_YIELD.value] is not None:
            self.q = self.parameters[PARAMETERS.DIVIDEND_YIELD.value]
        else:
            self.q = dividend_yield
        self.d1, self.d2 = self._calculate_d1_d2() if (self.T > 0 and self.sigma > 0) else [0.0, 0.0]

    def calculate_call_price(self) -> float:
        if (self.T <= 0 or self.sigma <= 0):
            return max(0.0, self.S - self.K)
        price = self.S * np.exp(-self.q * self.T) * norm.cdf(self.d1) - self.K * np.exp(-self.r * self.T) * norm.cdf(self.d2)
        return price
    
    def calculate_put_price(self) -> float:
        if (self.T <= 0 or self.sigma <= 0):
            return max(0.0, self.K - self.S)
        price = self.K * np.exp(-self.r * self.T) * norm.cdf(-self.d2) - self.S * np.exp(-self.q * self.T) * norm.cdf(-self.d1)
        return price
    
    def _calculate_d1_d2(self) -> float:
        d1 = (np.log(self.S/self.K) + (self.r - self.q + (0.5 * self.sigma**2)) * self.T)/ (self.sigma * np.sqrt(self.T))
        d2 = d1 - self.sigma * np.sqrt(self.T)

        return [d1, d2]