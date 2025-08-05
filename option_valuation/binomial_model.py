import numpy as np
from scipy.stats import norm

from .base_option import OptionValuationModel
from .enums_option import PARAMETERS

class BinomialModel(OptionValuationModel):
    def __init__(self, option_type, parameters):
        """
            Initialize parameters used to calculate call and put prices.
            Utilised the Risk Neutral Shortcut for calculations.
            Parameters:
                1. stock_price - Underlying stock price
                2. strike_price - Strike/ Exercise price
                3. days_to_expiry - Days to expiry
                4. interest_rate - Risk free interest rate
                5. volatility - Annualized volatility of stock in decimal (risk neutral probability)
                6. dividend_yeild - Stock dividend yield
                7. time_steps - Number of binomial steps, default 100
        """
        super().__init__(option_type, parameters)
        self.S = self.parameters[PARAMETERS.STOCK_PRICE.value]
        self.X = self.parameters[PARAMETERS.STRIKE_PRICE.value]
        self.T = self.parameters[PARAMETERS.DAYS_TO_EXPIRY.value] / 365
        self.r = self.parameters[PARAMETERS.INTEREST_RATE.value]
        self.sigma = self.parameters[PARAMETERS.VOLATILITY.value]
        self.q = self.parameters.get(PARAMETERS.DIVIDEND_YIELD.value, 0.0)
        self.N = self.parameters.get(PARAMETERS.TIME_STEPS.value, 100)

        self.delta_t = self.T/ self.N

        # Up, down factors
        self.u = np.exp(self.sigma * np.sqrt(self.delta_t))
        self.d = np.exp(-self.sigma * np.sqrt(self.delta_t))

        # risk neutral probability
        self.p = (np.exp((self.r - self.q) * self.delta_t) - self.d) / (self.u - self.d)

    def calculate_call_price(self):
        # Initializing option values
        asset_prices = np.zeros(self.N + 1)  # payout
        option_values = np.zeros(self.N + 1)  # profit

        # Calculating asset prices at terminal states (leaf nodes)
        for i in range(self.N+1):
            asset_prices[i] = self.S * (self.u ** i) * (self.d ** (self.N - i))
            option_values[i] = max(0, asset_prices[i] - self.X)

        # Backwards induction to calculate current option value
        """
        Backwards induction value = e^(-r(delta_t))*[p * V_up + (1-p)*V_down]
        Start from terminal nodes, move backward step by step to calc option vals at earlier nodes
            - since upper factor accounted first then d earlier, leaf nodes are in order of 0 upper to all upper from i=0 to i=-1
        """
        for step in range(self.N-1, -1, -1):
            for i in range(step+1):  # each step of the way
                option_values[i] = np.exp(-self.r * self.delta_t) * (self.p * option_values[i+1] + (1-self.p) * option_values[i])

        return option_values[0]
    
    def calculate_put_price(self):
        # Initializing option values
        asset_prices = np.zeros(self.N + 1)  # payout
        option_values = np.zeros(self.N + 1)  # profit

        # Calculating asset prices at terminal states (leaf nodes)
        for i in range(self.N+1):
            asset_prices[i] = self.S * (self.u ** i) * (self.d ** (self.N - i))
            option_values[i] = max(0, self.X-asset_prices[i])

        # Backwards induction to calculate current option value
        """
        Backwards induction value = e^(-r(delta_t))*[p * V_up + (1-p)*V_down]
        Start from terminal nodes, move backward step by step to calc option vals at earlier nodes
            - since upper factor accounted first then d earlier, leaf nodes are in order of 0 upper to all upper from i=0 to i=-1
        """
        for step in range(self.N-1, -1, -1):
            for i in range(step+1):  # each step of the way
                option_values[i] = np.exp(-self.r * self.delta_t) * (self.p * option_values[i+1] + (1-self.p) * option_values[i])

        return option_values[0]