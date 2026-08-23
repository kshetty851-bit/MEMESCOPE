"""STRATEGY DISCOVERY ENGINE — automated walk-forward search. **Research only.**

Generates a bounded family of strategy definitions, replays every one against
the *same* canonical opportunity stream Strategy Lab already publishes, and
reports which survive on data they were not designed on.

It recommends. It cannot activate: it writes only `strategy_lab_discovery_*`
tables, has no signer, and every route it exposes is a GET.
"""
