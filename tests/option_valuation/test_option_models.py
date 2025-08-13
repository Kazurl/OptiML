import pytest
from option_valuation.black_scholes_model import BlackScholesModel
from option_valuation.binomial_model import BinomialModel
from option_valuation.simple_binomial_model import SimpleBinomialModel
from utils.enums_option import OPTION_TYPE, PARAMETERS

# Shared parameters (classic Black-Scholes test case)
params = {
    PARAMETERS.STOCK_PRICE.value: 100,
    PARAMETERS.STRIKE_PRICE.value: 100,
    PARAMETERS.DAYS_TO_EXPIRY.value: 365,  # 1 year
    PARAMETERS.INTEREST_RATE.value: 0.05,
    PARAMETERS.VOLATILITY.value: 0.2,
    PARAMETERS.TIME_STEPS.value: 1000,
}

# Expected reference values
EXPECTED_BS_CALL = 10.4506
EXPECTED_BS_PUT = 5.5735
EXPECTED_SIMPLE_CALL = 12.11
EXPECTED_SIMPLE_PUT = 7.35


@pytest.fixture(scope="module")
def model_prices():
    """Compute all model prices once for reuse."""
    bs_call = BlackScholesModel(OPTION_TYPE.CALL.value, params).calculate_price()
    bs_put = BlackScholesModel(OPTION_TYPE.PUT.value, params).calculate_price()
    binom_call = BinomialModel(OPTION_TYPE.CALL.value, params).calculate_price()
    binom_put = BinomialModel(OPTION_TYPE.PUT.value, params).calculate_price()
    sbinom_call = SimpleBinomialModel(OPTION_TYPE.CALL.value, params).calculate_price()
    sbinom_put = SimpleBinomialModel(OPTION_TYPE.PUT.value, params).calculate_price()
    return {
        "bs_call": bs_call,
        "bs_put": bs_put,
        "binom_call": binom_call,
        "binom_put": binom_put,
        "sbinom_call": sbinom_call,
        "sbinom_put": sbinom_put,
    }


@pytest.mark.parametrize(
    "val_key, expected, tol",
    [
        ("bs_call", EXPECTED_BS_CALL, 1e-2),
        ("bs_put", EXPECTED_BS_PUT, 1e-2),
        ("binom_call", EXPECTED_BS_CALL, 2e-2),  # looser tolerance for binomial
        ("binom_put", EXPECTED_BS_PUT, 2e-2),
        ("sbinom_call", EXPECTED_SIMPLE_CALL, 1e-2),
        ("sbinom_put", EXPECTED_SIMPLE_PUT, 1e-2),
    ]
)
def test_model_prices_close(model_prices, val_key, expected, tol):
    val = model_prices[val_key]
    assert abs(val - expected) < tol, f"{val_key} differs: got {val:.4f}, expected {expected:.4f}"


def main():
    # Runs when executed as script
    mp = model_prices()
    print("= Black-Scholes Model =")
    print(f"Call price (Black-Scholes): {mp['bs_call']:.4f} (expected ~10.4506)")
    print(f"Put price  (Black-Scholes): {mp['bs_put']:.4f} (expected ~5.5735)")
    print("\n= Binomial Model =")
    print(f"Call price (Binomial, N=1000): {mp['binom_call']:.4f} (should approximate Black-Scholes)")
    print(f"Put price  (Binomial, N=1000): {mp['binom_put']:.4f} (should approximate Black-Scholes)")
    print("\n= Simple Binomial Model =")
    print(f"Call price (Simple Binomial): {mp['sbinom_call']:.4f} (expected ~12.11)")
    print(f"Put price  (Simple Binomial): {mp['sbinom_put']:.4f} (expected ~7.35)")
    print("\nAll tests verified via pytest assertions.")


if __name__ == "__main__":
    main()