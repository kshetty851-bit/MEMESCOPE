import re

with open("tests/unit/test_paper_strategy.py", "r") as f:
    content = f.read()

content = content.replace(
    "assert sum(1 for item in registry.all() if item.operational) == 1",
    "print([(item.id, item.operational) for item in registry.all() if item.operational])\n        assert sum(1 for item in registry.all() if item.operational) == 1"
)

with open("tests/unit/test_paper_strategy.py", "w") as f:
    f.write(content)

