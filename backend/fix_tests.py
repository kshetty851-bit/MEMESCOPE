import re

with open("tests/unit/test_paper_strategy.py", "r") as f:
    content = f.read()

content = content.replace(
    "assert registry.default.id == TRAILING_STOP_25_V1.id",
    "assert registry.default.id == 'paper_trailing_stop_25_time_v2'"
)

# And there is a test that uses StrategyRegistry((TRAILING_STOP_25_V1, other), default=TRAILING_STOP_25_V1.id)
# This test asserts exactly one strategy trades, so maybe other was set to operational=True. But TRAILING_STOP_25_V1 is operational=False now!
# We should import TRAILING_STOP_25_TIME_V2 and use it there.
content = content.replace("TRAILING_STOP_25_V1", "TRAILING_STOP_25_TIME_V2")
content = content.replace("from app.paper.strategy import (", "from app.paper.strategy import (\n    TRAILING_STOP_25_TIME_V2,")

with open("tests/unit/test_paper_strategy.py", "w") as f:
    f.write(content)
