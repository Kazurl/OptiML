import datetime
import itertools
import streamlit as st

from option_valuation.black_scholes_model import BlackScholesModel
from utils.enums_option import PARAMETERS, OPTION_TYPE

## ----------------------------------------------
# Declarations
BSM_params = {
    PARAMETERS.STOCK_PRICE.value: None,  # float
    PARAMETERS.STRIKE_PRICE.value: None,  # float
    PARAMETERS.DAYS_TO_EXPIRY.value: None,  # int
    PARAMETERS.INTEREST_RATE.value: None,  # float
    PARAMETERS.VOLATILITY.value: None,  # float
    PARAMETERS.DIVIDEND_YIELD.value: None,  # float
}
## ----------------------------------------------

def show_black_scholes_tab():
    leftCol, rightCol = st.columns([1, 3])
    BSM_output = None
    with leftCol:
        bsm_option_type = st.selectbox(
            "Option Type",
            [OPTION_TYPE.CALL.value, OPTION_TYPE.PUT.value],
            format_func=lambda x: x.split(" ")[0].capitalize(),
            placeholder=" ",
            index=None,
            key="bsm_option_type"
        )
        
        # Get Parameters=
        st.write("Enter your variables")
        BSM_params[PARAMETERS.STOCK_PRICE.value] = st.number_input(
            "Stock Price",
            key="BSM_S",
        )
        BSM_params[PARAMETERS.STRIKE_PRICE.value] = st.number_input(
            "Strike Price",
            key="BSM_X",
        )
        days_to_expiry_selection = st.pills(
            "Days to Expiry",
            options=[
                ("slider", ":material/sliders:"),
                ("num", ":material/keyboard_keys:"),
                ("date", ":material/date_range:")
            ],
            format_func=lambda x: x[1],
            key="BSM_T_mode"
        )
        days_to_expiry_selection = days_to_expiry_selection if days_to_expiry_selection else ("num", ":material/keyboard_keys:")
        if days_to_expiry_selection[0] == "num":
            BSM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = st.number_input(
                "days_to_expiry",
                label_visibility="hidden",
                min_value=1,
                max_value=3650,
                key="BSM_T_num",
            )
        elif days_to_expiry_selection[0] == "date":
            currDate = datetime.date.today()
            BSM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = (st.date_input(
                "days_to_expiry",
                label_visibility="hidden",
                min_value=datetime.date.today() + datetime.timedelta(days=1),
                key="BSM_T_date"
            ) - currDate).days
        else:
            BSM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = st.slider(
                "days_to_expiry",
                label_visibility="hidden",
                min_value=1,
                max_value=3650,
                key="BSM_T_slider"
            )
        BSM_params[PARAMETERS.INTEREST_RATE.value] = st.number_input(
            "Risk-Free Interest Rate (in %)",
            min_value=0.0,
            max_value=100.0,
            value=5.0,
            key="BSM_r"
        ) / 100.0
        BSM_params[PARAMETERS.VOLATILITY.value] = st.number_input(
            "Volatility (in %)",
            min_value=0.0,
            max_value=500.0,
            value=20.0,
            key="BSM_sigma"
        ) / 100.0
        BSM_params[PARAMETERS.DIVIDEND_YIELD.value] = st.number_input(
            "Dividend Yield (in %)",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            key="BSM_q"
        ) / 100.0
        # Output the values
        if st.button(f"Calculate {bsm_option_type} Premium", key="BSM_output"):
            if any(BSM_params[k] is None for k in BSM_params.keys()):
                st.toast("Missing Parameter Input!")
            else:
                # Initialize Model and store calculation
                BSM = BlackScholesModel(bsm_option_type, BSM_params)
                BSM_output = BSM.calculate_price()
                if BSM_output:
                    with st.spinner("Calculating..."):
                        st.write(f"{bsm_option_type.split(" ")[0].capitalize()} Price: {BSM_output:.4f}")

    with rightCol:
        st.write(BSM_params)
        if BSM_output:
            st.write(BSM_output)