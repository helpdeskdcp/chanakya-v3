"""
Chanakya AI — Complete Options Greeks Calculator
Black-Scholes model with Newton-Raphson IV solver
Greeks: Delta, Gamma, Theta, Vega, Rho, IV
"""
import math
from datetime import datetime
import pytz

# ── Risk-free rate (India 10Y ~7%) ─────────────────────
RISK_FREE_RATE = 0.07
IST = pytz.timezone("Asia/Kolkata")


def norm_cdf(x):
    """Standard normal CDF"""
    return (1 + math.erf(x / math.sqrt(2))) / 2


def norm_pdf(x):
    """Standard normal PDF"""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def get_time_to_expiry(expiry_str):
    """
    Returns time to expiry in years (T).
    expiry_str: '21APR2026' or datetime
    """
    try:
        now = datetime.now(IST)
        if isinstance(expiry_str, str):
            exp = datetime.strptime(expiry_str, "%d%b%Y")
        else:
            exp = expiry_str
        exp_ist = IST.localize(exp.replace(hour=15, minute=30))
        if exp_ist <= now:
            return 0.0001  # Expired but not zero
        delta_secs = (exp_ist - now).total_seconds()
        t = delta_secs / (365 * 24 * 3600)
        return max(t, 0.0001)
    except Exception:
        return 0.04167  # ~15 days fallback


def bs_price(spot, strike, t, r, sigma, opt_type):
    """Black-Scholes theoretical price"""
    try:
        if t <= 0 or sigma <= 0:
            # Intrinsic value only
            if opt_type == "CE":
                return max(0, spot - strike)
            else:
                return max(0, strike - spot)
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        if opt_type == "CE":
            return spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
        else:
            return strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    except Exception:
        return 0.0


def calc_all_greeks(spot, strike, t, r, sigma, opt_type):
    """
    Returns dict with all 5 Greeks + theoretical price.
    sigma: implied volatility (decimal, e.g. 0.18 = 18%)
    t: time to expiry in years
    """
    result = {
        "delta": 0.5 if opt_type == "CE" else -0.5,
        "gamma": 0.0,
        "theta": 0.0,
        "vega":  0.0,
        "rho":   0.0,
        "theo_price": 0.0,
    }
    try:
        if t <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
            return result

        d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        nd1 = norm_pdf(d1)
        sqrt_t = math.sqrt(t)
        exp_rt = math.exp(-r * t)

        # ── Delta ─────────────────────────────────────
        if opt_type == "CE":
            delta = norm_cdf(d1)
            theo  = spot * norm_cdf(d1) - strike * exp_rt * norm_cdf(d2)
            rho   = strike * t * exp_rt * norm_cdf(d2) / 100
        else:
            delta = norm_cdf(d1) - 1
            theo  = strike * exp_rt * norm_cdf(-d2) - spot * norm_cdf(-d1)
            rho   = -strike * t * exp_rt * norm_cdf(-d2) / 100

        # ── Gamma (same for CE/PE) ─────────────────────
        gamma = nd1 / (spot * sigma * sqrt_t)

        # ── Vega (per 1% IV change) ────────────────────
        vega = spot * nd1 * sqrt_t / 100

        # ── Theta (per calendar day) ───────────────────
        theta_ce = (
            -(spot * nd1 * sigma) / (2 * sqrt_t)
            - r * strike * exp_rt * norm_cdf(d2)
        ) / 365
        if opt_type == "CE":
            theta = theta_ce
        else:
            theta = (
                -(spot * nd1 * sigma) / (2 * sqrt_t)
                + r * strike * exp_rt * norm_cdf(-d2)
            ) / 365

        result.update({
            "delta":      round(delta,      4),
            "gamma":      round(gamma,      6),
            "theta":      round(theta,      4),
            "vega":       round(vega,       4),
            "rho":        round(rho,        4),
            "theo_price": round(max(0, theo), 2),
        })
    except Exception as e:
        pass
    return result


def calc_iv_newton(premium, spot, strike, t, r, opt_type, max_iter=100):
    """
    Implied Volatility via Newton-Raphson method.
    Returns IV as decimal (e.g. 0.18 for 18%)
    """
    try:
        if premium <= 0 or t <= 0 or spot <= 0 or strike <= 0:
            return 0.0

        # Initial sigma guess based on Brenner-Subrahmanyam approximation
        sigma = math.sqrt(2 * math.pi / t) * premium / spot
        sigma = max(0.05, min(sigma, 5.0))

        for _ in range(max_iter):
            try:
                d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
                d2 = d1 - sigma * math.sqrt(t)

                if opt_type == "CE":
                    price = spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
                else:
                    price = strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)

                vega = spot * norm_pdf(d1) * math.sqrt(t)
                if vega < 1e-10:
                    break

                diff = price - premium
                sigma -= diff / vega
                sigma = max(0.001, min(sigma, 10.0))

                if abs(diff) < 0.001:
                    break
            except (ValueError, ZeroDivisionError):
                break

        return round(sigma, 4) if 0 < sigma < 10 else 0.0
    except Exception:
        return 0.0


def black_scholes_delta(spot, strike, t, r, sigma, opt_type):
    """Backward-compatible delta function"""
    g = calc_all_greeks(spot, strike, t, r, sigma, opt_type)
    return g["delta"]


def get_moneyness(spot, strike, opt_type):
    """
    Returns: 'DEEP_ITM', 'ITM', 'ATM', 'OTM', 'DEEP_OTM'
    """
    pct = (spot - strike) / spot * 100
    if opt_type == "CE":
        if pct > 3:   return "DEEP_ITM"
        if pct > 0.5: return "ITM"
        if pct > -0.5: return "ATM"
        if pct > -3:  return "OTM"
        return "DEEP_OTM"
    else:  # PE
        if pct < -3:   return "DEEP_ITM"
        if pct < -0.5: return "ITM"
        if pct < 0.5:  return "ATM"
        if pct < 3:    return "OTM"
        return "DEEP_OTM"


def get_strike_selection(spot, step=50, count=6):
    """
    Returns ATM + ITM/OTM strikes for given step size.
    Returns list of strikes centered on ATM.
    """
    atm = round(spot / step) * step
    strikes = []
    for i in range(-count, count + 1):
        strikes.append(atm + i * step)
    return sorted(strikes), atm


# ── MCX step sizes ─────────────────────────────────────
MCX_STEPS = {
    "CRUDEOIL":   50,
    "NATURALGAS": 10,
    "GOLD":       100,
    "SILVER":     100,
    "COPPER":     5,
}

NSE_STEPS = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "FINNIFTY":   50,
    "MIDCPNIFTY": 25,
    "SENSEX":     100,
}
