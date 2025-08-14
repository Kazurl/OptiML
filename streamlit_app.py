import streamlit as st

from app.pages.db_viewer.db_viewer import show_database
from app.pages.option_valuation.binomial_tab import show_binomial_tab
from app.pages.option_valuation.black_scholes_tab import show_black_scholes_tab
from app.pages.option_valuation.simple_binomial_tab import show_simple_binomial_tab
from db.sqlite.db_utils import init_db

## ----------------------------------------------
# Initialize db
init_db()


## ----------------------------------------------
# Start of UI
st.title("OptiML Option Valuation")
st.divider()

# Choosing valuation method
st.write("Choose an option valuation model:")
BSM_tab, BM_tab, SBM_tab, db_tab = st.tabs(
    [ "Black Scholes Model", "Binomial Model", "Classic Binomial Model", "Database Viewer" ]
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

# DB tab
with db_tab:
    show_database()