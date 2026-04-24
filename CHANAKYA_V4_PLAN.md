# 🧠 CHANAKYA AI v4.0 — SMART DATA ENGINE
**Chanakya Niti: "जो शत्रूची चाल आधी ओळखतो — तोच जिंकतो"**
**Date:** April 25, 2026

---

## 🎯 OBJECTIVE
Live market data → Smart features → ML + Rules → High probability trade

---

## 🏗️ COMPLETE ARCHITECTURE
LAYER 1: DATA SOURCES
━━━━━━━━━━━━━━━━━━━━━
📊 Price Data      → OHLC 1m + 5m + 15m (Angel One API)
📉 Option Chain    → OI, Change OI, IV per strike (Angel One)
⚡ Volume Data     → Candle volume, Volume spike
🧠 FII/DII         → Daily bias (NSE website)
📰 News/Events     → RBI, Budget, Global (Economic Calendar)
LAYER 2: FEATURE ENGINE
━━━━━━━━━━━━━━━━━━━━━━━
Technical:
EMA 9, 20, 50        → Trend direction
RSI 14               → Overbought/Oversold
ADX 14               → Trend strength
VWAP                 → Institutional level
Volume Spike         → Confirmation (> 1.5x avg)
Bollinger Bands      → Squeeze/Breakout
Options Intelligence:
OI Buildup (Call)    → Resistance zone
OI Buildup (Put)     → Support zone
PCR (Put-Call Ratio) → Market sentiment
Max Pain Strike      → Price magnet
IV Percentile        → Cheap (<30) / Expensive (>70)
Change in OI         → Fresh positions
Greeks (Option DNA):
Delta                → Direction sensitivity
Gamma                → Speed of move
Theta                → Time decay per day
Vega                 → IV sensitivity
Market Structure:
Higher High/Low      → Uptrend confirmed
Lower High/Low       → Downtrend confirmed
VWAP Breakout        → Institutional move
Support/Resistance   → Key price levels
LAYER 3: MTF TREND ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━
15m → EMA20 vs EMA50 + ADX > 20 → MASTER TREND
5m  → EMA20 vs EMA50 + VWAP     → CONFIRMATION
1m  → RSI + Volume + Price Action → ENTRY TIMING
Rule:
15m UP + 5m UP    → BUY CE only
15m DOWN + 5m DOWN → BUY PE only
Conflict          → NO TRADE
LAYER 4: ML ENSEMBLE ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Model 1: XGBoost (42+ features)     → Probability
Model 2: Random Forest              → Probability
Model 3: Rule-based Engine          → Score 0-100
Voting:
2/3 agree bullish (prob > 0.65) → BUY CE
2/3 agree bearish (prob > 0.65) → BUY PE
No consensus                    → NO TRADE
LAYER 5: DECISION ENGINE (SCORE 0-100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
+30  MTF Trend match (15m + 5m agree)
+15  RSI signal (< 35 CE / > 65 PE)
+20  VWAP position (above=CE / below=PE)
+20  Volume spike (> 1.5x average)
+15  OI support/resistance aligned
+10  ML prob > 0.65
+10  ADX > 25 (strong trend)
-20  IV > 70 percentile (expensive)
-15  ADX < 20 (sideways)
-10  News in next 30 min
━━━━━━━━━━━━━━━━━━━━━━━━
Score >= 70 → EXECUTE TRADE ✅
Score 50-69 → MONITOR only ⚠️
Score < 50  → NO TRADE ❌
LAYER 6: OPTION SELECTION ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ATM Strike = round(spot / interval) * interval
NIFTY:      interval = 50
BANKNIFTY:  interval = 100
CRUDEOIL:   interval = 100
NATURALGAS: interval = 10
Strike Type:
TRENDING_UP/DOWN → ITM (delta ~0.6, more premium move)
SIDEWAYS         → ATM (delta ~0.5, balanced)
VOLATILE         → OTM (delta ~0.3, cheap but risky)
Expiry:
Weekly/Near expiry → More gamma, faster move
IV < 30%          → Buy (cheap)
IV > 70%          → Sell (expensive) / Avoid buying
LAYER 7: RISK ENGINE
━━━━━━━━━━━━━━━━━━━━
Entry:   Option LTP (live from Angel One)
SL:      entry * 0.85  (15% loss)
Target:  entry * 1.25  (25% gain) → R:R = 1.67
Trailing SL:
Profit > 10% → Move SL to cost (breakeven)
Profit > 20% → Trail SL by 5% steps
Profit > 40% → Trail SL by 3% steps (tighter)
Position Size:
Max 2% capital per trade
Max 3 open positions
Max 1 position per symbol
Exit Logic:
SL hit        → Exit immediately
Target hit    → Exit immediately
Opposite signal → Early exit (save profit)
Time 3:15 PM  → Force exit (no overnight)
LAYER 8: SMART FILTERS (NO TRADE ZONES)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Time:
9:15-9:20   → Skip (opening volatility)
11:30-12:00 → Skip (lunch lull)
15:15-15:30 → Skip (closing)
Market:
ADX < 20    → Sideways, skip
VIX > 25    → High fear, skip
Volume < 50% avg → Low participation, skip
Events:
RBI Policy day → Avoid options buying
Budget day     → Only sell premium
Global selloff → Wait for stabilization
LAYER 9: SELF-LEARNING ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every Trade Log:
entry_time, exit_time
entry_price, exit_price
features at entry (all 42+)
score, ml_probability
profit_loss, reason
Weekly Retrain:
New trades added to dataset
XGBoost + RF retrained
Feature importance updated
Weights adjusted
Self-Learning:
Win  strategy → weight +0.1
Loss strategy → weight -0.05
Consistent win pattern → auto increase allocation
---

## 📁 FILE STRUCTURE (Implementation)
engine/
├── mtf_engine.py        ← Multi-timeframe trend
├── options_intel.py     ← OI, PCR, Max Pain, IV
├── feature_engine.py    ← All 42+ features
├── decision_engine.py   ← Score + voting
├── risk_engine.py       ← SL/Target/Trailing
├── trade_manager.py     ← 5-sec monitoring
├── learning_engine.py   ← Per-trade logging
└── smart_filter.py      ← No-trade zones

---

## 📊 IMPLEMENTATION PHASES

### Phase 1 — MTF + Options Intel (Week 1)
- [ ] mtf_engine.py (1m/5m/15m)
- [ ] options_intel.py (OI, PCR, Max Pain)
- [ ] feature_engine.py (42+ features)
- [ ] Test on historical data

### Phase 2 — Decision Engine (Week 2)
- [ ] decision_engine.py (score 0-100)
- [ ] ML ensemble voting
- [ ] Backtest 3 months
- [ ] Paper trade validation

### Phase 3 — Risk + Trade Manager (Week 3)
- [ ] risk_engine.py
- [ ] trade_manager.py (5-sec monitor)
- [ ] smart_filter.py
- [ ] Live paper trade 2 weeks

### Phase 4 — Self-Learning (Week 4+)
- [ ] learning_engine.py
- [ ] Per-trade logging
- [ ] Weekly retrain pipeline
- [ ] Performance dashboard

---

## 💰 REALISTIC EXPECTATIONS
Current system:  ~60-65% accuracy (estimated)
After Phase 1:   ~68-72% (MTF filter)
After Phase 2:   ~72-76% (ensemble)
After Phase 3:   ~74-78% (risk control)
After Phase 4:   ~76-80% (self-learning)
IMPORTANT — Chanakya's Rule:
"शत्रू (market) को कभी underestimate मत करो"
No system wins 100%
Capital protection > profit
2 weeks paper minimum before live
Start with 1 lot only
---

## ⚠️ CHANAKYA'S GOLDEN RULES
"अधूरी जानकारी से लड़ाई मत करो"
→ Never trade without signal confirmation
"जो सब कर रहे हैं — वो मत करो"
→ Trade when score >= 70, not FOMO
"धन की रक्षा पहले, बढ़ाना बाद में"
→ SL is mandatory, always
"गलती से सीखो, दोहराओ मत"
→ Log every trade, analyze weekly
"एक युद्ध जीतने के लिए 100 योजनाएं बनाओ"
→ Backtest before live
---

**Ready to implement Phase 1? 🚀**
