from app.labs.graduation import dip_buy as db

DIP = [(1, 1e-7, 100.0), (10, 2e-7, 100.0), (25, 1.4e-7, 100.0)]    # 30% under the peak at 30 s


def test_buys_a_dip_with_a_short_name_and_sells_at_five_minutes():
    t = db.decide([*DIP, (400, 1.4e-7, 100.0)], "ABC")
    assert t and t["how"] == "5m" and t["held_s"] == 300
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
