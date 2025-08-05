import datetime
import streamlit as st

from option_valuation.simple_binomial_model import SimpleBinomialModel
from utils.enums_option import PARAMETERS, OPTION_TYPE

## ----------------------------------------------
# Declarations
SBM_params = {
    PARAMETERS.STOCK_PRICE.value: None,  # float
    PARAMETERS.STRIKE_PRICE.value: None,  # float
    PARAMETERS.INTEREST_RATE.value: None,  # float
    PARAMETERS.VOLATILITY.value: None,  # float
    PARAMETERS.DIVIDEND_YIELD.value: None,  # float
}
## ----------------------------------------------

def show_simple_binomial_tab():
    leftCol, rightCol = st.columns([1, 3])
    SBM_output = None
    with leftCol:
        sbm_option_type = st.selectbox(
            "Option Type",
            [OPTION_TYPE.CALL.value, OPTION_TYPE.PUT.value],
            format_func=lambda x: x.split(" ")[0].capitalize(),
            placeholder=" ",
            index=None,
            key="sbm_option_type"
        )
        
        # Get Parameters
        st.write("Enter your variables")
        SBM_params[PARAMETERS.STOCK_PRICE.value] = st.number_input(
            "Stock Price",
            key="SBM_S",
        )
        SBM_params[PARAMETERS.STRIKE_PRICE.value] = st.number_input(
            "Strike Price:",
            key="SBM_X",
        )
        SBM_params[PARAMETERS.INTEREST_RATE.value] = st.number_input(
            "Risk-Free Interest Rate (in %)",
            min_value=0.0,
            max_value=100.0,
            value=5.0,
            key="SBM_r"
        ) / 100.0
        SBM_params[PARAMETERS.VOLATILITY.value] = st.number_input(
            "Volatility (in %)",
            min_value=0.0,
            max_value=500.0,
            value=20.0,
            key="SBM_sigma"
        ) / 100.0
        SBM_params[PARAMETERS.DIVIDEND_YIELD.value] = st.number_input(
            "Dividend Yield (in %)",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            key="SBM_q"
        ) / 100.0
        SBM_params
        # Output the values
        if st.button(f"Calculate {sbm_option_type} Premium", key="SBM_output"):
            if any(SBM_params[k] is None for k in SBM_params.keys()):
                st.toast("Missing Parameter Input!")
            else:
                # Initialize Model and store calculation
                SBM = SimpleBinomialModel(sbm_option_type, SBM_params)
                SBM_output = SBM.calculate_price()
                if SBM_output:
                    with st.spinner("Calculating..."):
                        st.write(f"{sbm_option_type.capitalize()} Price: {SBM_output:.4f}")

    with rightCol:
        st.write(SBM_params)
        if SBM_output:
            st.write(SBM_output)