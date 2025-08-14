import streamlit as st

from app.components.plot_payoff_profit import show_plot_payoff_profit
from app.components.plot_premium_price import show_plot_premium_price
from db.sqlite.db_utils import insert_run_to_db
from option_valuation.simple_binomial_model import SimpleBinomialModel
from utils.enums_option import PARAMETERS, OPTION_MODEL, OPTION_TYPE

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
                        insert_run_to_db(OPTION_MODEL.SIMPLE_BINOMIAL_MODEL.value, SBM_params, SBM_output)
                        st.write(f"{sbm_option_type.capitalize()} Price: {SBM_output:.4f}")

    with rightCol:
        st.write(SBM_params)
        if SBM_output:
            st.write({"Premium": SBM_output})
            curStockPrice = SBM_params[PARAMETERS.STOCK_PRICE.value]

            # plot payout against price
            fig_payoutprice = show_plot_payoff_profit(
                sbm_option_type,
                SBM_params[PARAMETERS.STRIKE_PRICE.value],
                SBM_output,
                [curStockPrice*0.5, curStockPrice*1.5, 100]
            )
            st.pyplot(fig_payoutprice)

            # plot premium against price
            fig_premiumprice = show_plot_premium_price(
                sbm_option_type,
                OPTION_MODEL.SIMPLE_BINOMIAL_MODEL.value,
                [curStockPrice*0.5, curStockPrice*1.5, 100],
                SBM_params[PARAMETERS.STRIKE_PRICE.value],
                T=None,
                r=SBM_params[PARAMETERS.INTEREST_RATE.value],
                sigma=SBM_params[PARAMETERS.VOLATILITY.value],
                q=SBM_params[PARAMETERS.DIVIDEND_YIELD.value],
            )
            st.pyplot(fig_premiumprice)