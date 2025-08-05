import datetime
import itertools
import streamlit as st

from option_valuation.binomial_model import BinomialModel
from option_valuation.black_scholes_model import BlackScholesModel
from option_valuation.simple_binomial_model import SimpleBinomialModel
from utils.enums_option import OPTION_MODEL, OPTION_TYPE, PARAMETERS

## ----------------------------------------------
# Declarations
option_type = {
    OPTION_TYPE.CALL.value: None,  # string
    OPTION_TYPE.PUT.value: None,  # string
}
params = {
    PARAMETERS.STOCK_PRICE.value: None,  # float
    PARAMETERS.STRIKE_PRICE.value: None,  # float
    PARAMETERS.DAYS_TO_EXPIRY.value: None,  # int
    PARAMETERS.INTEREST_RATE.value: None,  # float
    PARAMETERS.VOLATILITY.value: None,  # float
    PARAMETERS.DIVIDEND_YIELD.value: None,  # float

    # Binomial Model
    PARAMETERS.TIME_STEPS.value: None,  # int (max 1000)

    # Classic/ Simple Binomial Model
    PARAMETERS.UP_FACTOR.value: None,  # float
    PARAMETERS.DOWN_FACTOR.value: None,   # float
}

###
#Params Usage:
#- BSM: params.keys()[:5]
#- BM: params.keys()[:6]
#- SBM: params.keys()[:2], [3], [7:]
###
## ----------------------------------------------


## ----------------------------------------------
# Start of UI
st.title("OptiML Option Valuation")
st.divider()

# Choosing valuation method
st.write("Choose an option valuation model:")
BSM_tab, BM_tab, SBM_tab = st.tabs(
    [ "Black Scholes Model", "Binomial Model", "Classic Binomial Model"]
)

# BSM tab
with BSM_tab:
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
        if option_type == "call option":
            st.toast("CALL OPTION!", icon=":material/warning:")
        
        # Get Parameters
        BSM_params = dict(itertools.islice(params.items(), 6))
        st.write("Enter your variables")
        BSM_params[PARAMETERS.STOCK_PRICE.value] = st.number_input(
            "Stock Price",
            key="BSM_S",
        )
        BSM_params[PARAMETERS.STRIKE_PRICE.value] = st.number_input(
            "Strike Price:",
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
                "",
                label_visibility="hidden",
                min_value=1,
                max_value=3650,
                key="BSM_T_num",
            )
        elif days_to_expiry_selection[0] == "date":
            currDate = datetime.date.today()
            BSM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = (st.date_input(
                "",
                label_visibility="hidden",
                min_value=datetime.date.today() + datetime.timedelta(days=1),
                key="BSM_T_date"
            ) - currDate).days
        else:
            BSM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = st.slider(
                "",
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
                        st.write(f"{bsm_option_type.capitalize()} Price: {BSM_output:.4f}")

    with rightCol:
        st.write(BSM_params)
        if BSM_output:
            st.write(BSM_output)

# BM tab
with BM_tab:
    leftCol, rightCol = st.columns([1, 3])
    with leftCol:
        bm_option_type = st.selectbox(
            "Option Type",
            [OPTION_TYPE.CALL.value, OPTION_TYPE.PUT.value],
            format_func=lambda x: x.split(" ")[0].capitalize(),
            placeholder=" ",
            index=None,
            key="bm_option_type"
        )

        # Initialize Model and store calculation

        # Output the values
        if st.button(f"Calculate {bm_option_type} Premium", key="BM_output"):
            with st.spinner("Calculating..."):
                st.write("OUTPUT")

# BSM tab
with SBM_tab:
    leftCol, rightCol = st.columns([1, 3])
    with leftCol:
        sbm_option_type = st.selectbox(
            "Option Type",
            [OPTION_TYPE.CALL.value, OPTION_TYPE.PUT.value],
            format_func=lambda x: x.split(" ")[0].capitalize(),
            placeholder=" ",
            index=None,
            key="sbm_option_type"
        )

        # Initialize Model and store calculation

        # Output the values
        if st.button(f"Calculate {sbm_option_type} Premium", key="SBM_output"):
            with st.spinner("Calculating..."):
                st.write("OUTPUT")