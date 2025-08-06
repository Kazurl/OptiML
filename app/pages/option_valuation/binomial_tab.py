import datetime
import streamlit as st

from app.components.plot_payoff_profit import show_plot_payoff_profit
from app.components.plot_premium_price import show_plot_premium_price
from option_valuation.binomial_model import BinomialModel
from utils.enums_option import PARAMETERS, OPTION_MODEL, OPTION_TYPE

## ----------------------------------------------
# Declarations
BM_params = {
    PARAMETERS.STOCK_PRICE.value: None,  # float
    PARAMETERS.STRIKE_PRICE.value: None,  # float
    PARAMETERS.DAYS_TO_EXPIRY.value: None,  # int
    PARAMETERS.INTEREST_RATE.value: None,  # float
    PARAMETERS.VOLATILITY.value: None,  # float
    PARAMETERS.DIVIDEND_YIELD.value: None,  # float
    PARAMETERS.TIME_STEPS.value: None,  # int (max 1000)
}
## ----------------------------------------------

def show_binomial_tab():
    leftCol, rightCol = st.columns([1, 3])
    BM_output = None
    with leftCol:
        bm_option_type = st.selectbox(
            "Option Type",
            [OPTION_TYPE.CALL.value, OPTION_TYPE.PUT.value],
            format_func=lambda x: x.split(" ")[0].capitalize(),
            placeholder=" ",
            index=None,
            key="bm_option_type"
        )
        
        # Get Parameters=
        st.write("Enter your variables")
        BM_params[PARAMETERS.STOCK_PRICE.value] = st.number_input(
            "Stock Price",
            key="BM_S",
        )
        BM_params[PARAMETERS.STRIKE_PRICE.value] = st.number_input(
            "Strike Price",
            key="BM_X",
        )
        days_to_expiry_selection = st.pills(
            "Days to Expiry",
            options=[
                ("slider", ":material/sliders:"),
                ("num", ":material/keyboard_keys:"),
                ("date", ":material/date_range:")
            ],
            format_func=lambda x: x[1],
            key="BM_T_mode"
        )
        days_to_expiry_selection = days_to_expiry_selection if days_to_expiry_selection else ("num", ":material/keyboard_keys:")
        if days_to_expiry_selection[0] == "num":
            BM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = st.number_input(
                "days_to_expiry",
                label_visibility="hidden",
                min_value=1,
                max_value=3650,
                key="BM_T_num",
            )
        elif days_to_expiry_selection[0] == "date":
            currDate = datetime.date.today()
            BM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = (st.date_input(
                "days_to_expiry",
                label_visibility="hidden",
                min_value=datetime.date.today() + datetime.timedelta(days=1),
                key="BM_T_date"
            ) - currDate).days
        else:
            BM_params[PARAMETERS.DAYS_TO_EXPIRY.value] = st.slider(
                "days_to_expiry",
                label_visibility="hidden",
                min_value=1,
                max_value=3650,
                key="BM_T_slider"
            )
        BM_params[PARAMETERS.INTEREST_RATE.value] = st.number_input(
            "Risk-Free Interest Rate (in %)",
            min_value=0.0,
            max_value=100.0,
            value=5.0,
            key="BM_r"
        ) / 100.0
        BM_params[PARAMETERS.VOLATILITY.value] = st.number_input(
            "Volatility (in %)",
            min_value=0.0,
            max_value=500.0,
            value=20.0,
            key="BM_sigma"
        ) / 100.0
        BM_params[PARAMETERS.DIVIDEND_YIELD.value] = st.number_input(
            "Dividend Yield (in %)",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            key="BM_q"
        ) / 100.0
        BM_params[PARAMETERS.TIME_STEPS.value] = st.number_input(
            "Time steps",
            min_value=0,
            value=100,
            key="BM_N"
        )
        st.caption("Higher steps result in longer loads")
        # Output the values
        if st.button(f"Calculate {bm_option_type} Premium", key="BM_output"):
            if any(BM_params[k] is None for k in BM_params.keys()):
                st.toast("Missing Parameter Input!")
            else:
                # Initialize Model and store calculation
                BM = BinomialModel(bm_option_type, BM_params)
                BM_output = BM.calculate_price()
                if BM_output:
                    with st.spinner("Calculating..."):
                        st.write(f"{bm_option_type.split(" ")[0].capitalize()} Price: {BM_output:.4f}")

    with rightCol:
        st.write(BM_params)
        if BM_output:
            st.write({"Premium": BM_output})
            curStockPrice = BM_params[PARAMETERS.STOCK_PRICE.value]

            # plot payout against price
            fig_payoutprice = show_plot_payoff_profit(
                bm_option_type,
                BM_params[PARAMETERS.STRIKE_PRICE.value],
                BM_output,
                [curStockPrice*0.5, curStockPrice*1.5, 100]
            )
            st.pyplot(fig_payoutprice)

            # plot premium against price
            fig_premiumprice = show_plot_premium_price(
                bm_option_type,
                OPTION_MODEL.BINOMIAL_MODEL.value,
                [curStockPrice*0.5, curStockPrice*1.5, 100],
                BM_params[PARAMETERS.STRIKE_PRICE.value],
                BM_params[PARAMETERS.DAYS_TO_EXPIRY.value],
                BM_params[PARAMETERS.INTEREST_RATE.value],
                BM_params[PARAMETERS.VOLATILITY.value],
                BM_params[PARAMETERS.DIVIDEND_YIELD.value],
                N=BM_params[PARAMETERS.TIME_STEPS.value]
            )
            st.pyplot(fig_premiumprice)