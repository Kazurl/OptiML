import streamlit as st

from app.pages.option_valuation.binomial_tab import show_binomial_tab
from app.pages.option_valuation.black_scholes_tab import show_black_scholes_tab
from app.pages.option_valuation.simple_binomial_tab import show_simple_binomial_tab

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
    show_black_scholes_tab()
# BM tab
with BM_tab:
    show_binomial_tab()

# BSM tab
with SBM_tab:
    show_simple_binomial_tab()