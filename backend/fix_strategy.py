import re

with open("app/paper/strategy.py", "r") as f:
    content = f.read()

# Fix the duplicate dataclass decorators
content = content.replace(
"""@dataclass(frozen=True, slots=True)

@dataclass(frozen=True, slots=True)
class TrailingStopStrategyV2:""",
"""@dataclass(frozen=True)
class TrailingStopStrategyV2:"""
)

with open("app/paper/strategy.py", "w") as f:
    f.write(content)

