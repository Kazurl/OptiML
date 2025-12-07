from utils.enums_option import PRETTY_PARAMETERS

def fnum(x, n=2) -> str:
    try: return f"{float(x):,.{n}f}"
    except Exception: return "n/a"
    
def pct(x) -> str:
    try: return f"{float(x)*100:.2f}%"
    except Exception: return "n/a"

def fpct(p) -> str:
    if p is None:
        return "n/a"
    try:
        return f"{float(p):.2f}%"
    except Exception:
        return "n/a"
    
def inst_name_formatter(base: str, date: str, strike: float, opt_type: str) -> str:
    """
    Format instrument name for options.
    date: in format DDMMMYY, e.g. 30DEC22 but sahve leading zero if single digit day, e.g. 5JAN23
    strike: int
    opt_type: "C" or "P"
    return: instrument name string,
    e.g. BTC-30DEC22-40000-C
    """
    date = date[1:] if date[0] == "0" else date
    opt_type = opt_type.upper()
    return f"{base}-{date}-{int(strike)}-{opt_type}"

def val_to_str_formatter(base: str, col: str, val) -> str:
    """
    Formats values of options to be accurate or of fixed size.
    """
    if col == PRETTY_PARAMETERS.SPOT_PRICE.value:
        return fnum(val)
    elif col == PRETTY_PARAMETERS.STRIKE_PRICE.value:
        return fnum(val, 0)
    elif col == PRETTY_PARAMETERS.OPTION_MID.value+f" ({base})" or col == base:
        return fnum(val, 6)
    elif col == PRETTY_PARAMETERS.OPTION_MID.value+" (USD)" or col == "USD":
        return fnum(val, 2)
    elif col == PRETTY_PARAMETERS.FAIR_PRICE.value:
        return fnum(val, 2)
    elif col == PRETTY_PARAMETERS.PRICE_DIFF.value:
        return fnum(val, 2)
    elif col == PRETTY_PARAMETERS.DAYS_TO_EXPIRY.value:
        return fnum(val, 1)
    else:
        return val