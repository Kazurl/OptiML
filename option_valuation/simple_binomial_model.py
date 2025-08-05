import numpy as np
from scipy.stats import norm

from .base_option import OptionValuationModel
from utils.enums_option import PARAMETERS

class SimpleBinomialModel(OptionValuationModel):
    def __init__(self, option_type, parameters):
        """
            Initialize parameters used to calculate call and put prices.
            Utilised the basic Risk Neutral Shortcut with no time step consideration for calculations.
            Parameters:
                1. stock_price - Stock price currently
                2. strike price - Strike price/ exercise price
                3. interest_rate - Risk free interest rate
                4. dividend_yeild - Stock dividend yield
                5. volatility - Volatlity of stock
        """
        super().__init__(option_type, parameters)
        self.S = self.parameters[PARAMETERS.STOCK_PRICE.value]
        self.X = self.parameters[PARAMETERS.STRIKE_PRICE.value]
        self.r = self.parameters[PARAMETERS.INTEREST_RATE.value]

        # Calculate up and down factors
        self.u = np.exp(self.parameters[PARAMETERS.VOLATILITY.value])
        self.d = np.exp(-self.parameters[PARAMETERS.VOLATILITY.value])

        # classic risk neutral probability
        self.p = (1 + self.r - self.d)/ (self.u - self.d)

    def calculate_call_price(self):
        # upper and lower payouts at expiry
        Su = max(self.S * self.u - self.X, 0)
        Sd = max(self.S * self.d - self.X, 0)
        price = (self.p * Su + (1-self.p) * Sd)/ (1 + self.r)

        return price
    
    def calculate_put_price(self):
        # upper and lower payouts at expiry
        Su = max(self.X - self.S * self.u, 0)
        Sd = max(self.X - self.S * self.d, 0)
        price = (self.p * Su + (1-self.p) * Sd)/ (1 + self.r)

        return price