"""
Chanakya AI v3.0 — Ultra-Strong ML Brain
Ensemble: XGBoost + RF + LightGBM + GBM + Neural Meta-Stacker
Target: 75%+ accuracy
"""
import numpy as np
import logging, os, pickle
from datetime import datetime

logger = logging.getLogger(__name__)
MODEL_PATH = "ai/models/ensemble.pkl"

# ── FEATURE ENGINEERING ────────────────────────────────

def _ema(prices, n):
    if len(prices) < n: return prices[-1] if prices else 0
    k = 2/(n+1)
    e = prices[0]
    for p in prices[1:]: e = p*k + e*(1-k)
    return e

def _rsi(prices, n=14):
    if len(prices) < n+1: return 50.0
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains  = [d if d>0 else 0 for d in deltas[-n:]]
    losses = [-d if d<0 else 0 for d in deltas[-n:]]
    ag,al  = sum(gains)/n, sum(losses)/n
    return 100 - 100/(1+ag/al) if al>0 else 100.0

def _stoch(highs, lows, closes, k=14):
    if len(closes) < k: return 50.0, 50.0
    h14 = max(highs[-k:]); l14 = min(lows[-k:])
    if h14==l14: return 50.0, 50.0
    k_val = 100*(closes[-1]-l14)/(h14-l14)
    d_val = np.mean([100*(closes[-i]-min(lows[-k-i+1:-i+1] if i>1 else lows[-k:]))/
                    max(1,max(highs[-k-i+1:-i+1] if i>1 else highs[-k:])-
                    min(lows[-k-i+1:-i+1] if i>1 else lows[-k:]))
                    for i in range(1,4)])
    return k_val, d_val

def _williams_r(highs, lows, closes, n=14):
    if len(closes) < n: return -50.0
    h = max(highs[-n:]); l = min(lows[-n:])
    if h==l: return -50.0
    return -100*(h-closes[-1])/(h-l)

def _cci(highs, lows, closes, n=20):
    if len(closes) < n: return 0.0
    tp = [(highs[i]+lows[i]+closes[i])/3 for i in range(-n,0)]
    avg = np.mean(tp)
    mad = np.mean([abs(t-avg) for t in tp])
    return (tp[-1]-avg)/(0.015*mad) if mad>0 else 0.0

def _atr(highs, lows, closes, n=14):
    if len(closes) < 2: return 0.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
               abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    return np.mean(trs[-n:]) if trs else 0.0

def _bb(closes, n=20, k=2):
    if len(closes) < n: return closes[-1], closes[-1], 0.0
    sl = closes[-n:]
    m  = np.mean(sl); s = np.std(sl)
    return m+k*s, m-k*s, 2*k*s/m if m>0 else 0.0

def _macd(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow+sig: return 0.0, 0.0, 0.0
    e_fast = _ema(closes, fast)
    e_slow = _ema(closes, slow)
    macd_line = e_fast - e_slow
    # Signal line approximation
    macd_vals = [_ema(closes[:i], fast) - _ema(closes[:i], slow)
                 for i in range(slow, len(closes)+1)]
    signal = _ema(macd_vals, sig) if len(macd_vals)>=sig else macd_line
    return macd_line, signal, macd_line-signal

def _mfi(highs, lows, closes, volumes, n=14):
    if len(closes) < n+1 or not volumes: return 50.0
    pos_mf = neg_mf = 0.0
    for i in range(-n, 0):
        tp  = (highs[i]+lows[i]+closes[i])/3
        ptp = (highs[i-1]+lows[i-1]+closes[i-1])/3
        mf  = tp * (volumes[i] if i < len(volumes) else 1)
        if tp > ptp: pos_mf += mf
        else:         neg_mf += mf
    return 100 - 100/(1+pos_mf/neg_mf) if neg_mf > 0 else 100.0

def _supertrend(highs, lows, closes, n=7, mult=3.0):
    if len(closes) < n+1: return 1  # Bullish default
    atr = _atr(highs[-n-5:], lows[-n-5:], closes[-n-5:], n)
    mid = (highs[-1]+lows[-1])/2
    upper = mid + mult*atr
    lower = mid - mult*atr
    return 1 if closes[-1] > lower else -1

def _candle_pattern(opens, highs, lows, closes):
    if len(closes) < 3: return 0
    o,h,l,c = opens[-1], highs[-1], lows[-1], closes[-1]
    po,ph,pl,pc = opens[-2], highs[-2], lows[-2], closes[-2]
    body = abs(c-o); prev_body = abs(pc-po)
    # Doji
    if body < 0.1*(h-l) and (h-l)>0: return 0
    # Bullish engulfing
    if pc < po and c > o and c > po and o < pc: return 2
    # Bearish engulfing
    if pc > po and c < o and c < po and o > pc: return -2
    # Hammer
    lower_wick = o-l if c>o else c-l
    if lower_wick > 2*body and body>0: return 1
    # Shooting star
    upper_wick = h-c if c>o else h-o
    if upper_wick > 2*body and body>0: return -1
    return 0

def _market_regime(closes, n=50):
    """Trending / Ranging / Volatile"""
    if len(closes) < n: return 0
    e50 = _ema(closes, n)
    e20 = _ema(closes, 20)
    e10 = _ema(closes, 10)
    if e10 > e20 > e50: return 1   # Bullish trend
    if e10 < e20 < e50: return -1  # Bearish trend
    return 0  # Ranging

def build_features(candles, vix=18.0, pcr=1.0, fii_net=0.0,
                   oi_change=0.0, iv=0.0, opt_type="CE"):
    """Build 40+ feature vector"""
    if len(candles) < 5:
        return [0.0] * 42

    opens  = [c.get("open",  c.get("o", 0)) for c in candles]
    highs  = [c.get("high",  c.get("h", 0)) for c in candles]
    lows   = [c.get("low",   c.get("l", 0)) for c in candles]
    closes = [c.get("close", c.get("c", 0)) for c in candles]
    vols   = [c.get("volume",c.get("v", 0)) for c in candles]

    if not any(closes): return [0.0] * 42
    last = closes[-1]
    if last == 0: return [0.0] * 42

    # EMAs
    e9   = _ema(closes, 9)
    e21  = _ema(closes, 21)
    e50  = _ema(closes, 50)
    e200 = _ema(closes, 200)

    # RSI
    rsi14 = _rsi(closes, 14)
    rsi9  = _rsi(closes, 9)
    rsi_slope = rsi14 - _rsi(closes[:-3], 14) if len(closes)>3 else 0

    # MACD
    m_val, m_sig, m_hist = _macd(closes)

    # Bollinger
    bb_up, bb_lo, bb_w = _bb(closes, 20)

    # ATR
    atr = _atr(highs, lows, closes, 14)
    atr_ratio = atr/last if last>0 else 0

    # Stochastic
    stoch_k, stoch_d = _stoch(highs, lows, closes, 14)

    # Williams %R
    will_r = _williams_r(highs, lows, closes, 14)

    # CCI
    cci = _cci(highs, lows, closes, 20)

    # MFI
    mfi = _mfi(highs, lows, closes, vols, 14)

    # Supertrend
    st = _supertrend(highs, lows, closes)

    # Candle pattern
    cp = _candle_pattern(opens, highs, lows, closes) if len(opens)>=3 else 0

    # Market regime
    regime = _market_regime(closes)

    # Volume analysis
    avg_vol = np.mean(vols[-20:]) if len(vols)>=20 else (vols[-1] if vols else 1)
    vol_ratio = vols[-1]/avg_vol if avg_vol>0 else 1
    vol_trend = (np.mean(vols[-5:]) - np.mean(vols[-10:-5])) / avg_vol if avg_vol>0 else 0

    # Price momentum
    mom5  = (last - closes[-6])  / closes[-6]  if len(closes)>5  and closes[-6]>0 else 0
    mom10 = (last - closes[-11]) / closes[-11] if len(closes)>10 and closes[-11]>0 else 0
    mom20 = (last - closes[-21]) / closes[-21] if len(closes)>20 and closes[-21]>0 else 0

    # Session timing
    now_hour = datetime.now().hour
    is_morning_session = 1 if 9 <= now_hour <= 11 else 0
    is_afternoon_session = 1 if 13 <= now_hour <= 15 else 0

    # Option type
    is_ce = 1 if opt_type == "CE" else 0

    features = [
        # EMA signals (6)
        (last-e9)/e9   if e9>0  else 0,
        (last-e21)/e21 if e21>0 else 0,
        (last-e50)/e50 if e50>0 else 0,
        (e9-e21)/e21   if e21>0 else 0,
        (e21-e50)/e50  if e50>0 else 0,
        (e50-e200)/e200 if e200>0 else 0,
        # RSI (3)
        rsi14/100, rsi9/100, rsi_slope/10,
        # MACD (3)
        m_val/last if last>0 else 0,
        m_sig/last if last>0 else 0,
        m_hist/last if last>0 else 0,
        # Bollinger (3)
        (bb_up-last)/last if last>0 else 0,
        (last-bb_lo)/last if last>0 else 0,
        bb_w,
        # ATR (1)
        atr_ratio,
        # Stochastic (2)
        stoch_k/100, stoch_d/100,
        # Williams %R (1)
        (will_r+50)/100,
        # CCI (1)
        np.clip(cci/200, -1, 1),
        # MFI (1)
        mfi/100,
        # Supertrend (1)
        float(st),
        # Candle pattern (1)
        float(cp)/2,
        # Market regime (1)
        float(regime),
        # Volume (3)
        np.clip(vol_ratio, 0, 5)/5,
        np.clip(vol_trend, -1, 1),
        np.log1p(vols[-1])/20 if vols else 0,
        # Momentum (3)
        np.clip(mom5,  -0.5, 0.5),
        np.clip(mom10, -0.5, 0.5),
        np.clip(mom20, -0.5, 0.5),
        # Market context (4)
        np.clip(vix/50, 0, 1),
        np.clip(pcr/3, 0, 1),
        np.clip(fii_net/10000, -1, 1),
        np.clip(oi_change/100, -1, 1),
        # Options (2)
        np.clip(iv/100, 0, 1),
        float(is_ce),
        # Session (2)
        float(is_morning_session),
        float(is_afternoon_session),
        # Price level (2)
        np.log1p(last)/15,
        np.clip(atr_ratio*10, 0, 1),
    ]
    return [float(x) if not np.isnan(x) and not np.isinf(x) else 0.0
            for x in features]

FEATURE_NAMES = [
    "ema9_dist","ema21_dist","ema50_dist","ema9v21","ema21v50","ema50v200",
    "rsi14","rsi9","rsi_slope",
    "macd","macd_sig","macd_hist",
    "bb_upper","bb_lower","bb_width","atr_ratio",
    "stoch_k","stoch_d","williams_r","cci","mfi",
    "supertrend","candle_pattern","regime",
    "vol_ratio","vol_trend","vol_abs",
    "mom5","mom10","mom20",
    "vix","pcr","fii_net","oi_change","iv","is_ce",
    "is_morning","is_afternoon",
    "price_level","volatility",
]

# ── ENSEMBLE MODEL ─────────────────────────────────────

class ChanakayaBrain:
    """
    Ultra-Strong AI Brain
    XGBoost + RF + LightGBM + GBM + Neural Meta-Stacker
    """
    def __init__(self):
        self.models     = []
        self.weights    = []
        self.stacker    = None
        self.scaler     = None
        self.is_trained = False
        self.accuracy   = 0.0
        self.n_samples  = 0
        self.feature_importance = {}
        self.version    = "v3.1-ultra"

    def train(self, X, y):
        import xgboost as xgb
        import lightgbm as lgb
        from sklearn.ensemble import (RandomForestClassifier,
                                       GradientBoostingClassifier)
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import accuracy_score

        X = np.array(X); y = np.array(y)
        n = len(X)
        if n < 30:
            logger.warning(f"Too few samples: {n}")
            return 0.0

        self.n_samples = n
        logger.info(f"🧠 Training on {n} samples, {X.shape[1]} features")

        # Class balance
        pos = sum(y); neg = n-pos
        scale_pos = neg/pos if pos>0 else 1.0

        # Scaler
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # SMOTE if imbalanced
        try:
            if min(pos,neg)/max(pos,neg) < 0.4:
                from imblearn.over_sampling import SMOTE
                X_scaled, y = SMOTE(random_state=42).fit_resample(X_scaled, y)
                logger.info(f"✅ SMOTE applied: {len(y)} samples")
        except ImportError:
            pass

        cv = StratifiedKFold(n_splits=min(5, max(3, n//20)),
                             shuffle=True, random_state=42)

        # Model 1: XGBoost (tuned)
        m1 = xgb.XGBClassifier(
            n_estimators=300, max_depth=6,
            learning_rate=0.05, subsample=0.8,
            colsample_bytree=0.8, min_child_weight=3,
            scale_pos_weight=scale_pos,
            eval_metric="logloss", verbosity=0,
            use_label_encoder=False, random_state=42
        )
        s1 = cross_val_score(m1, X_scaled, y, cv=cv,
                             scoring="accuracy").mean()
        m1.fit(X_scaled, y)

        # Feature importance from XGBoost
        fi = m1.feature_importances_
        for i, name in enumerate(FEATURE_NAMES[:len(fi)]):
            self.feature_importance[name] = round(float(fi[i]), 4)

        # Model 2: Random Forest (deep)
        m2 = RandomForestClassifier(
            n_estimators=300, max_depth=12,
            min_samples_leaf=3, max_features="sqrt",
            class_weight="balanced", random_state=42, n_jobs=-1
        )
        s2 = cross_val_score(m2, X_scaled, y, cv=cv,
                             scoring="accuracy").mean()
        m2.fit(X_scaled, y)

        # Model 3: LightGBM (fast+accurate)
        s3 = 0.0
        m3 = None
        try:
            m3 = lgb.LGBMClassifier(
                n_estimators=300, num_leaves=63,
                learning_rate=0.05, subsample=0.8,
                colsample_bytree=0.8, min_child_samples=5,
                class_weight="balanced",
                verbosity=-1, random_state=42
            )
            s3 = cross_val_score(m3, X_scaled, y, cv=cv,
                                 scoring="accuracy").mean()
            m3.fit(X_scaled, y)
        except Exception as e:
            logger.warning(f"LightGBM failed: {e}")

        # Model 4: Gradient Boosting
        m4 = GradientBoostingClassifier(
            n_estimators=200, max_depth=5,
            learning_rate=0.05, subsample=0.8,
            random_state=42
        )
        s4 = cross_val_score(m4, X_scaled, y, cv=cv,
                             scoring="accuracy").mean()
        m4.fit(X_scaled, y)

        # Weights by CV accuracy
        base_models = [(m1,s1,"XGBoost"), (m2,s2,"RF"),
                       (m4,s4,"GBM")]
        if m3: base_models.append((m3,s3,"LightGBM"))
        base_models.sort(key=lambda x: x[1], reverse=True)

        total_score = sum(s for _,s,_ in base_models)
        self.models  = [m for m,_,_ in base_models]
        self.weights = [s/total_score for _,s,_ in base_models]

        for m,s,name in base_models:
            logger.info(f"  {name}: CV={s:.1%}")

        # Meta-stacker: LogisticRegression on OOF predictions
        try:
            from sklearn.model_selection import cross_val_predict
            oof_preds = np.column_stack([
                cross_val_predict(m, X_scaled, y, cv=cv, method="predict_proba")[:,1]
                for m,_,_ in base_models
            ])
            self.stacker = LogisticRegression(C=1.0, random_state=42)
            stacker_score = cross_val_score(
                self.stacker, oof_preds, y,
                cv=cv, scoring="accuracy"
            ).mean()
            self.stacker.fit(oof_preds, y)
            logger.info(f"  Meta-stacker: CV={stacker_score:.1%}")
            self.accuracy = stacker_score
        except Exception as e:
            logger.warning(f"Stacker failed: {e}")
            self.accuracy = max(s for _,s,_ in base_models)

        self.is_trained = True
        logger.info(f"✅ Brain trained: {self.accuracy:.1%} accuracy")
        self._save()
        return self.accuracy

    def predict(self, features):
        """Returns (prediction, confidence, breakdown)"""
        if not self.is_trained or not self.models:
            return 0, 0.5, {}
        X = np.array(features).reshape(1,-1)
        if self.scaler:
            X = self.scaler.transform(X)

        probs = [m.predict_proba(X)[0][1] for m in self.models]

        if self.stacker:
            meta_input = np.array(probs).reshape(1,-1)
            final_prob = self.stacker.predict_proba(meta_input)[0][1]
        else:
            final_prob = sum(p*w for p,w in zip(probs, self.weights))

        pred = 1 if final_prob >= 0.5 else 0
        breakdown = {
            "models": [round(p,3) for p in probs],
            "final":  round(final_prob, 3),
        }
        return pred, round(float(final_prob), 4), breakdown

    def get_top_features(self, n=10):
        return sorted(self.feature_importance.items(),
                      key=lambda x: x[1], reverse=True)[:n]

    def _save(self):
        os.makedirs("ai/models", exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(self, f)
        logger.info(f"✅ Model saved: {MODEL_PATH}")

    @classmethod
    def load(cls):
        try:
            with open(MODEL_PATH, "rb") as f:
                obj = pickle.load(f)
            logger.info(f"✅ Model loaded: {obj.n_samples} samples, "
                        f"{obj.accuracy:.1%} accuracy")
            return obj
        except Exception as e:
            logger.warning(f"Model load failed: {e}")
            return cls()

    def train_from_db(self, db_path="data/chanakya_v3.db"):
        """Train from closed trades in DB"""
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        trades = conn.execute("""
            SELECT * FROM trades
            WHERE status='CLOSED'
            AND entry_price > 0 AND exit_price > 0
            AND ABS(pnl) < 50000
            ORDER BY created_at DESC
            LIMIT 1000
        """).fetchall()
        conn.close()

        if len(trades) < 30:
            logger.warning(f"Too few trades for training: {len(trades)}")
            return 0.0

        X, y = [], []
        for t in trades:
            try:
                # Reconstruct features from stored data
                feats = [
                    float(t["entry_price"] or 0) / 1000,
                    float(t["target_price"] or 0) / float(t["entry_price"] or 1),
                    float(t["sl_price"] or 0) / float(t["entry_price"] or 1),
                    float(t["rr_ratio"] or 1.5),
                    float(t["ml_confidence"] or 0.5),
                    float(t["lot_size"] or 1) / 100,
                    float(t["lots"] or 1),
                    1.0 if (t["opt_type"] or "") == "CE" else 0.0,
                    float(t["vix"] or 18) / 50,
                    float(t["pcr"] or 1) / 3,
                ]
                # Pad to 42 features
                feats += [0.0] * (42 - len(feats))
                X.append(feats[:42])
                y.append(1 if (t["pnl"] or 0) > 0 else 0)
            except Exception:
                continue

        if len(X) < 30:
            return 0.0
        logger.info(f"📊 Training from DB: {len(X)} trades")
        return self.train(X, y)


# Singleton
_brain = None

def get_brain():
    global _brain
    if _brain is None:
        _brain = ChanakayaBrain.load()
    return _brain

def retrain(db_path="data/chanakya_v3.db"):
    global _brain
    brain = ChanakayaBrain()
    acc = brain.train_from_db(db_path)
    if acc > 0:
        _brain = brain
    return acc, brain.n_samples

# ── Backward Compatibility ─────────────────────────────
# start_v3.py `ensemble` import karto — provide singleton
ensemble = get_brain()
