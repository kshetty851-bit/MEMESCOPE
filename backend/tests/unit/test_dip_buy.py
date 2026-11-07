from app.labs.graduation import dip_buy as db

DIP = [(1, 1e-7, 100.0), (10, 2e-7, 100.0), (25, 1.4e-7, 100.0)]    # 30% under the peak at 30 s
QUIET = [(1, 1e-7, 50.0), (15, 1e-7, 49.0)]                         # 49 SOL at 20 s, 2% off its high


def test_buys_a_dip_with_a_short_name_and_sells_at_five_minutes():
    t = db.decide([*DIP, (400, 1.4e-7, 100.0)], "ABC")
    assert t and t["rule"] == "dip" and t["how"] == "time" and t["held_s"] == 300
    assert -0.05 < t["ret"] < 0          # a flat price loses only the fees and slippage


def test_target_fills_at_the_reading_after_it_reaches_sixty_percent():
    t = db.decide([*DIP, (100, 2.4e-7, 100.0), (120, 2.2e-7, 100.0)], "ABC")
    assert t["how"] == "target" and t["held_s"] == 90
    assert t["exit_px"] == 2.2e-7


def test_a_target_on_the_last_reading_sells_there():
    t = db.decide([*DIP, (100, 2.4e-7, 100.0)], "ABC")
    assert t["how"] == "target" and t["exit_px"] == 2.4e-7


def test_refuses_shallow_and_deep_dips_long_names_tiny_pools_and_late_recordings():
    assert db.decide([(1, 1e-7, 100.0), (25, 0.9e-7, 100.0)], "ABC") is None
    assert db.decide([(1, 1e-7, 100.0), (25, 0.5e-7, 100.0)], "ABC") is None
    assert db.decide(DIP, "LONGNAME") is None
    assert db.decide(DIP, "  ") is None
    assert db.decide([(1, 2e-7, 20.0), (25, 1.4e-7, 20.0)], "ABC") is None
    assert db.decide([(20, 2e-7, 100.0), (25, 1.4e-7, 100.0)], "ABC") is None


def test_quiet_small_pool_buys_at_20_s_and_holds_7_minutes():
    t = db.decide([*QUIET, (500, 1e-7, 49.0)], "ANYLONGNAME")
    assert t["rule"] == "quiet" and t["entry_s"] == 20 and t["how"] == "time" and t["held_s"] == 420


def test_quiet_stop_fills_at_the_reading_after_minus_35():
    t = db.decide([*QUIET, (60, 0.6e-7, 40.0), (70, 0.5e-7, 38.0)], None)
    assert t["how"] == "stop" and t["exit_px"] == 0.5e-7 and t["held_s"] == 50


def test_quiet_needs_a_small_pool_nobody_has_sold_into():
    assert db.decide([(1, 1e-7, 50.0), (15, 1e-7, 45.0)], None) is None        # 10% off its high
    assert db.decide([(1, 1e-7, 70.0), (15, 1e-7, 70.0)], None) is None        # too big
    assert db.decide([(1, 1e-7, 25.0), (15, 1e-7, 25.0)], None) is None        # too small
