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