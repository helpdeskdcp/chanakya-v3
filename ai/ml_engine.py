"""
Chanakya v3 — Ensemble ML Engine
XGBoost + Random Forest + LightGBM + Meta-Stacker
"""
import os, logging, pickle, json
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)
MODEL_DIR = "ai/models"
os.makedirs(MODEL_DIR, exist_ok=True)

# ── Feature Engineering ────────────────────────────────
def build_features(candles, vix=18.0, pcr=1.0, fii_net=0.0,
                   iv=0.0, delta=0.5, theta=0.0, days_left=0):
    """
    Build 47-feature vector from market data.
    Returns numpy array or None if insufficient data.
    """
    if len(candles) < 60:
        return None

    closes  = [c[4] for c in candles]
    highs   = [c[2] for c in candles]
    lows    = [c[3] for c in candles]
    opens   = [c[1] for c in candles]
    vols    = [c[5] for c in candles] if len(candles[0]) > 5 else [1]*len(candles)

    # ── Price Action Features (15) ─────────
    from engine.signals import ema, rsi, macd, atr

    ema9   = ema(closes, 9)
    ema21  = ema(closes, 21)
    ema50  = ema(closes, 50)
    ema200 = ema(closes, 200) if len(closes) >= 200 else [closes[-1]]

    rsi14  = rsi(closes, 14)
    rsi9   = rsi(closes, 9)
    rsi_slope = rsi14 - rsi(closes[:-5], 14) if len(closes) > 5 else 0

    m_val, m_sig, m_hist = macd(closes)
    atr14 = atr(candles, 14)
    atr_avg = atr(candles[-28:], 14) if len(candles) >= 28 else atr14
    atr_ratio = atr14 / atr_avg if atr_avg > 0 else 1.0

    last = closes[-1]
    e9   = ema9[-1]  if ema9  else last
    e21  = ema21[-1] if ema21 else last
    e50  = ema50[-1] if ema50 else last
    e200 = ema200[-1] if ema200 else last

    bb_mid = sum(closes[-20:]) / 20
    bb_std = (sum((c - bb_mid)**2 for c in closes[-20:]) / 20) ** 0.5
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0

    price_features = [
        (last - e9)   / e9   if e9   > 0 else 0,  # Price vs EMA9
        (last - e21)  / e21  if e21  > 0 else 0,  # Price vs EMA21
        (last - e50)  / e50  if e50  > 0 else 0,  # Price vs EMA50
        (last - e200) / e200 if e200 > 0 else 0,  # Price vs EMA200
        (e9 - e21)    / e21  if e21  > 0 else 0,  # EMA9 vs EMA21
        rsi14 / 100,                                # RSI14 normalized
        rsi9  / 100,                                # RSI9 normalized
        rsi_slope / 10,                             # RSI momentum
        m_val  / last if last > 0 else 0,           # MACD normalized
        m_sig  / last if last > 0 else 0,           # MACD signal
        m_hist / last if last > 0 else 0,           # MACD histogram
        (bb_upper - last) / last if last > 0 else 0, # Distance to upper BB
        (last - bb_lower) / last if last > 0 else 0, # Distance to lower BB
        bb_width,                                   # BB width
        atr_ratio,                                  # ATR ratio
    ]

    # ── Volume Features (8) ────────────────
    avg_vol = sum(vols[-20:]) / 20 if sum(vols[-20:]) > 0 else 1
    vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 1

    # OBV
    obv = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:   obv += vols[i]
        elif closes[i] < closes[i-1]: obv -= vols[i]
    obv_norm = obv / (sum(vols) + 1)

    # MFI
    tp = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(closes))]
    pmf = sum(tp[i]*vols[i] for i in range(1, len(tp)) if tp[i] > tp[i-1])
    nmf = sum(tp[i]*vols[i] for i in range(1, len(tp)) if tp[i] < tp[i-1])
    mfi = 100 - 100/(1 + pmf/nmf) if nmf > 0 else 50

    # VWAP deviation
    vwap_val = sum(tp[i]*vols[i] for i in range(len(tp))) / (sum(vols) + 1)
    vwap_dev = (last - vwap_val) / vwap_val if vwap_val > 0 else 0

    volume_features = [
        min(vol_ratio / 3, 3),           # Volume ratio (capped)
        obv_norm,                         # OBV normalized
        vwap_dev,                         # VWAP deviation
        mfi / 100,                        # MFI normalized
        1 if vol_ratio > 2 else 0,        # Volume spike flag
        # CMF proxy
        (last - lows[-1]) / (highs[-1] - lows[-1]) if highs[-1] > lows[-1] else 0.5,
        # Price momentum 5-bar
        (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0,
        # Price momentum 10-bar
        (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0,
    ]

    # ── Options Features (12) ──────────────
    options_features = [
        iv / 100,                          # IV normalized
        min(iv / 30, 3),                   # IV vs avg (30% baseline)
        pcr,                               # PCR
        min(pcr / 2, 2),                   # PCR ratio
        abs(delta),                        # |Delta|
        delta + 0.5,                       # Delta shifted (0-1)
        abs(theta) / last if last > 0 else 0,  # Theta normalized
        1 if iv > 20 else 0,               # High IV flag
        1 if pcr > 1.2 else 0,             # Bearish PCR flag
        1 if pcr < 0.8 else 0,             # Bullish PCR flag
        days_left / 30,                    # Time to expiry normalized
        1 if days_left <= 3 else 0,        # Expiry week flag
    ]

    # ── Market Context (12) ────────────────
    now = datetime.now()
    hour_norm    = (now.hour - 9) / 7      # 9AM-4PM normalized
    fii_norm     = max(-1, min(1, fii_net / 2000))  # FII flow normalized
    vix_norm     = vix / 30                # VIX normalized

    # Recent candle patterns
    last3 = closes[-3:]
    trend_up   = 1 if all(last3[i] > last3[i-1] for i in range(1, len(last3))) else 0
    trend_down = 1 if all(last3[i] < last3[i-1] for i in range(1, len(last3))) else 0

    context_features = [
        vix_norm,                          # VIX level
        1 if vix > 20 else 0,              # High VIX flag
        fii_norm,                          # FII net flow
        1 if fii_net > 500 else 0,         # Strong FII buying
        1 if fii_net < -500 else 0,        # Strong FII selling
        hour_norm,                         # Hour of day
        now.weekday() / 4,                 # Day of week (Mon=0)
        1 if now.weekday() == 0 else 0,    # Monday flag
        1 if now.weekday() == 4 else 0,    # Friday flag
        trend_up,                          # 3-bar uptrend
        trend_down,                        # 3-bar downtrend
        # Volatility regime
        1 if atr_ratio > 1.5 else 0,       # High volatility flag
    ]

    features = price_features + volume_features + options_features + context_features
    assert len(features) == 47, f"Expected 47 features, got {len(features)}"
    return np.array(features, dtype=np.float32)


# ── Ensemble Model ─────────────────────────────────────
class EnsembleModel:
    def __init__(self):
        self.models     = {}
        self.weights    = {}
        self.is_trained = False
        self.accuracy   = 0.0
        self.n_samples  = 0
        self.trained_at = None

    def train(self, X, y):
        """Train all 4 models + meta-stacker"""
        if len(X) < 50:
            logger.warning(f"Too few samples: {len(X)}")
            return False
        try:
            from sklearn.model_selection import cross_val_score, StratifiedKFold
            from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
            import xgboost as xgb

            cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
            X = np.array(X); y = np.array(y)

            # Model 1: XGBoost
            m1 = xgb.XGBClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                eval_metric='logloss', use_label_encoder=False,
                random_state=42
            )
            s1 = cross_val_score(m1, X, y, cv=cv, scoring='accuracy').mean()
            m1.fit(X, y)

            # Model 2: Random Forest
            m2 = RandomForestClassifier(
                n_estimators=300, max_depth=10,
                min_samples_split=5, random_state=42
            )
            s2 = cross_val_score(m2, X, y, cv=cv, scoring='accuracy').mean()
            m2.fit(X, y)

            # Model 3: LightGBM
            try:
                import lightgbm as lgb
                m3 = lgb.LGBMClassifier(
                    n_estimators=200, max_depth=8,
                    learning_rate=0.05, random_state=42,
                    verbose=-1
                )
                s3 = cross_val_score(m3, X, y, cv=cv, scoring='accuracy').mean()
                m3.fit(X, y)
            except ImportError:
                m3 = m2  # Fallback to RF
                s3 = s2

            # Model 4: Gradient Boosting
            m4 = GradientBoostingClassifier(
                n_estimators=150, max_depth=5,
                learning_rate=0.1, random_state=42
            )
            s4 = cross_val_score(m4, X, y, cv=cv, scoring='accuracy').mean()
            m4.fit(X, y)

            # Meta-stacker: weighted logistic regression
            total = s1 + s2 + s3 + s4
            w1, w2, w3, w4 = s1/total, s2/total, s3/total, s4/total

            self.models  = {"xgb": m1, "rf": m2, "lgbm": m3, "gbm": m4}
            self.weights = {"xgb": w1, "rf":  w2, "lgbm": w3, "gbm": w4}
            self.accuracy   = (s1+s2+s3+s4) / 4
            self.n_samples  = len(X)
            self.is_trained = True
            self.trained_at = datetime.now().isoformat()

            logger.info(f"✅ Ensemble trained: XGB={s1:.2%} RF={s2:.2%} LGBM={s3:.2%} GBM={s4:.2%}")
            logger.info(f"✅ Avg accuracy: {self.accuracy:.2%} | Samples: {len(X)}")

            self.save()
            return True
        except Exception as e:
            logger.error(f"Training error: {e}")
            import traceback; traceback.print_exc()
            return False

    def predict(self, features):
        """Returns (signal, confidence) tuple"""
        if not self.is_trained or features is None:
            return "NEUTRAL", 0.0
        try:
            X = features.reshape(1, -1)
            probs = []
            for name, model in self.models.items():
                w = self.weights.get(name, 0.25)
                p = model.predict_proba(X)[0]
                probs.append(p * w)
            avg_prob = np.sum(probs, axis=0)
            pred_class = np.argmax(avg_prob)
            confidence = round(float(avg_prob[pred_class]) * 100, 1)
            signal = "BUY" if pred_class == 1 else "SELL"
            return signal, confidence
        except Exception as e:
            logger.error(f"Predict error: {e}")
            return "NEUTRAL", 0.0

    def save(self):
        try:
            with open(f"{MODEL_DIR}/ensemble.pkl", "wb") as f:
                pickle.dump({
                    "models": self.models,
                    "weights": self.weights,
                    "accuracy": self.accuracy,
                    "n_samples": self.n_samples,
                    "trained_at": self.trained_at,
                }, f)
            logger.info(f"✅ Model saved to {MODEL_DIR}/ensemble.pkl")
        except Exception as e:
            logger.error(f"Save error: {e}")

    def load(self):
        path = f"{MODEL_DIR}/ensemble.pkl"
        if not os.path.exists(path):
            logger.info("No saved model found")
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.models     = data["models"]
            self.weights    = data["weights"]
            self.accuracy   = data.get("accuracy", 0)
            self.n_samples  = data.get("n_samples", 0)
            self.trained_at = data.get("trained_at", "")
            self.is_trained = True
            logger.info(f"✅ Model loaded: {self.n_samples} samples, {self.accuracy:.2%} accuracy")
            return True
        except Exception as e:
            logger.error(f"Load error: {e}")
            return False

# Singleton
ensemble = EnsembleModel()
ensemble.load()
