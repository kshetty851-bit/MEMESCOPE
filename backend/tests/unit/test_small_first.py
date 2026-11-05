from app.labs.graduation import small_first as sf

FLAT = [(1, 1e-7, 100.0), (400, 1e-7, 100.0)]


def test_buys_a_small_first_short_name_and_sells_at_five_minutes():
    t = sf.decide(FLAT, "ABC")
    assert t and t["how"] == "5m" and t["held_s"] == 300
    assert -0.05 < t["ret"] < 0          # a flat price loses only the fees and slippage (~3.6%)


def test_target_sells_on_the_first_reading_up_thirty_percent_after_costs():
    t = sf.decide([(1, 1e-7, 100.0), (100, 1.2e-7, 100.0), (200, 1.5e-7, 100.0)], "ABC")
    assert t["how"] == "target" and t["held_s"] == 155 and t["ret"] >= 0.30


def test_refuses_long_names_big_first_buys_tiny_pools_and_late_recordings():
    assert sf.decide(FLAT, "LONGNAME") is None
    assert sf.decide(FLAT, "  ") is None
    assert sf.decide([(1, 1e-7, 150.0)], "ABC") is None
    assert sf.decide([(1, 1e-7, 50.0)], "ABC") is None
    assert sf.decide([(20, 1e-7, 100.0)], "ABC") is None
