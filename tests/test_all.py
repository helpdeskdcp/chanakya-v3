"""
Chanakya v3 — Unit Tests
"""
import sys, os
sys.path.insert(0, '/root/chanakya_v3')
import unittest

class TestConfig(unittest.TestCase):
    def test_config_load(self):
        from config import config
        self.assertEqual(config.VERSION, "3.0.0")
        self.assertGreater(config.MIN_RR, 0)
        self.assertGreater(config.MAX_CAPITAL_PCT, 0)

class TestDatabase(unittest.TestCase):
    def test_init_db(self):
        from data.database import init_db, get_today_stats
        init_db()
        stats = get_today_stats()
        self.assertIn("total", stats)
        self.assertIn("pnl", stats)

class TestGreeks(unittest.TestCase):
    def test_bs_price(self):
        from engine.greeks import bs_price, calc_all_greeks
        price = bs_price(24000, 24000, 0.04, 0.07, 0.18, "CE")
        self.assertGreater(price, 0)

    def test_all_greeks(self):
        from engine.greeks import calc_all_greeks
        g = calc_all_greeks(24000, 24000, 0.04, 0.07, 0.18, "CE")
        self.assertIn("delta", g)
        self.assertIn("gamma", g)
        self.assertIn("theta", g)
        self.assertIn("vega", g)
        self.assertGreater(g["delta"], 0)
        self.assertLess(g["delta"], 1)

    def test_iv_newton(self):
        from engine.greeks import calc_iv_newton
        iv = calc_iv_newton(200, 24000, 24000, 0.04, 0.07, "CE")
        self.assertGreater(iv, 0)
        self.assertLess(iv, 3)

class TestSignals(unittest.TestCase):
    def test_ema(self):
        from engine.signals import ema
        prices = list(range(1, 31))
        result = ema(prices, 9)
        self.assertGreater(len(result), 0)

    def test_rsi(self):
        from engine.signals import rsi
        import random
        prices = [100 + random.uniform(-5,5) for _ in range(30)]
        r = rsi(prices)
        self.assertGreaterEqual(r, 0)
        self.assertLessEqual(r, 100)

    def test_atr(self):
        from engine.signals import atr
        candles = [[i, 100+i, 105+i, 95+i, 102+i, 1000]
                   for i in range(20)]
        a = atr(candles)
        self.assertGreater(a, 0)

    def test_smc_order_blocks(self):
        from engine.signals import SmartMoneySMC
        smc = SmartMoneySMC()
        candles = [[i, 100, 110, 90, 105, 1000] for i in range(25)]
        obs = smc.detect_order_blocks(candles)
        self.assertIsInstance(obs, list)

    def test_market_structure(self):
        from engine.signals import SmartMoneySMC
        smc = SmartMoneySMC()
        # Uptrend candles
        candles = [[i, 90+i, 100+i, 85+i, 95+i, 1000] for i in range(25)]
        s = smc.market_structure(candles)
        self.assertIn(s, ["UPTREND","DOWNTREND","CONSOLIDATION","REVERSAL","UNKNOWN"])

class TestRisk(unittest.TestCase):
    def test_vix_check(self):
        from engine.risk import check_vix
        ok, msg = check_vix(18)
        self.assertTrue(ok)
        ok2, msg2 = check_vix(30)
        self.assertFalse(ok2)

    def test_rr_check(self):
        from engine.risk import check_rr
        ok, msg = check_rr(100, 90, 120, 100000, 1, 75)
        self.assertTrue(ok)
        ok2, msg2 = check_rr(100, 99, 101, 100000, 1, 75)
        self.assertFalse(ok2)  # R:R too low

    def test_kelly(self):
        from engine.risk import RiskEngine
        r = RiskEngine()
        size = r.kelly_position_size(100000, 0.6, 2.0)
        self.assertGreater(size, 0)
        self.assertLessEqual(size, 2000)

    def test_time_check(self):
        from engine.risk import check_time
        ok, msg = check_time()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

class TestMarket(unittest.TestCase):
    def test_market_status(self):
        from data.market import get_market_status
        s = get_market_status()
        self.assertIn("nse_open", s)
        self.assertIn("session", s)
        self.assertIn("expiry_day", s)

    def test_market_regime(self):
        from data.market import get_market_regime
        r = get_market_regime(vix=18, pcr=1.0, fii_net=200)
        self.assertIn(r, ["BULL","BEAR","MILD_BULL","MILD_BEAR",
                          "SIDEWAYS","VOLATILE","CAUTION"])

    def test_size_multiplier(self):
        from data.market import get_size_multiplier
        m = get_size_multiplier("VOLATILE", 25)
        self.assertLessEqual(m, 0.5)
        m2 = get_size_multiplier("BULL", 14)
        self.assertGreaterEqual(m2, 0.9)

class TestMLEngine(unittest.TestCase):
    def test_model_load(self):
        from ai.ml_engine import ensemble
        # Should have loaded from disk
        self.assertIsNotNone(ensemble)

    def test_predict_format(self):
        from ai.ml_engine import ensemble
        import numpy as np
        if ensemble.is_trained:
            feat = np.random.rand(15).astype(np.float32)
            sig, conf = ensemble.predict(feat)
            self.assertIn(sig, ["BUY", "SELL", "NEUTRAL"])
            self.assertGreaterEqual(conf, 0)
            self.assertLessEqual(conf, 100)

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"\n{'='*50}")
    print(f"✅ PASSED: {passed}/{result.testsRun}")
    if result.failures or result.errors:
        print(f"❌ FAILED: {len(result.failures)+len(result.errors)}")
    print(f"{'='*50}")
