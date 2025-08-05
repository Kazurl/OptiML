import numpy as np

from option_valuation.black_scholes_model import BlackScholesModel
from option_valuation.binomial_model import BinomialModel
from option_valuation.enums_option import OPTION_TYPE, PARAMETERS
from option_valuation.simple_binomial_model import SimpleBinomialModel

# Known parameters (classic Black-Scholes test case with no dividends)
params = {
    PARAMETERS.STOCK_PRICE.value: 100,
    PARAMETERS.STRIKE_PRICE.value: 100,
    PARAMETERS.DAYS_TO_EXPIRY.value: 365,  # 1 year
    PARAMETERS.INTEREST_RATE.value: 0.05,  # as decimals
    PARAMETERS.VOLATILITY.value: 0.2,  # as decimals
    # Omit dividend yield for vanilla comparison

    # Binomial Model
    PARAMETERS.TIME_STEPS.value: 1000,

    # Classic/ Simple Binomial Model
    PARAMETERS.UP_FACTOR.value: np.exp(0.2 * np.sqrt(1)),
    PARAMETERS.DOWN_FACTOR.value: np.exp(-0.2 * np.sqrt(1)) 
}

# Known analytical solutions for Black-Scholes (rounded for demonstration)
# Call ~ 10.4506, Put ~ 5.5735 for above parameters

print("=== Black-Scholes Model ===")
bs_call = BlackScholesModel(OPTION_TYPE.CALL.value, params).calculate_price()
bs_put = BlackScholesModel(OPTION_TYPE.PUT.value, params).calculate_price()
print(f"Call price (Black-Scholes): {bs_call:.4f} (expected ~10.4506)")
print(f"Put price  (Black-Scholes): {bs_put:.4f} (expected ~5.5735)")

print("\n=== Binomial Model ===")
binom_call = BinomialModel(OPTION_TYPE.CALL.value, params).calculate_price()
binom_put = BinomialModel(OPTION_TYPE.PUT.value, params).calculate_price()
print(f"Call price (Binomial, N=1000): {binom_call:.4f} (should approximate Black-Scholes)")
print(f"Put price  (Binomial, N=1000): {binom_put:.4f} (should approximate Black-Scholes)")

print("\n=== Simple Binomial Model ===")
sbinom_call = SimpleBinomialModel(OPTION_TYPE.CALL.value, params).calculate_price()
sbinom_put = SimpleBinomialModel(OPTION_TYPE.PUT.value, params).calculate_price()
print(f"Call price (Simple Binomial): {sbinom_call:.4f} (expected ~12.11)")
print(f"Put price  (Simple Binomial): {sbinom_put:.4f} (expected ~7.35)")

# Optional: assert tests for automated runs
def test_close(val1, val2, tol=1e-2):
    assert abs(val1 - val2) < tol, f"Values differ: {val1} vs {val2}"

test_close(bs_call, 10.4506)  # Max allowance 5 cents diff
test_close(bs_put, 5.5735)
test_close(binom_call, bs_call, tol=2e-2)
test_close(binom_put, bs_put, tol=2e-2)
test_close(sbinom_call, 12.11)
test_close(sbinom_put, 7.35)

print("\nAll tests passed.")
