"""Pump Catcher Lab's exit: +30% target filled at the next reading, else 10 minutes."""

from app.labs.graduation.pump_catcher import decide


def test_target_hit_fills_at_the_next_reading_not_the_trigger():
    path = [(60, 1.05), (300, 1.12), (420, 1.31), (450, 1.25), (600, 1.4)]
    out = decide(path, net5=0.10)                       # cost = 0.12 - 0.10 = 0.02
    assert out["how"] == "target" and out["held_s"] == 450
    assert round(out["net"], 4) == round(1.25 - 1 - 0.02, 4)


def test_no_target_sells_at_ten_minutes():
    path = [(60, 1.0), (300, 0.98), (590, 0.9), (610, 0.4), (900, 0.1)]
    out = decide(path, net5=-0.03)                      # cost = -0.02 + 0.03 = 0.01
    assert out["how"] == "10m" and out["held_s"] == 610
    assert round(out["net"], 4) == round(0.4 - 1 - 0.01, 4)


def test_readings_that_disagree_with_the_book_keep_the_five_minute_result():
    path = [(60, 1.0), (300, 3.0), (600, 3.1)]          # the feed jumped pools
    assert decide(path, net5=0.02) == {"net": 0.02, "held_s": 300, "gross": None, "how": "5m"}
