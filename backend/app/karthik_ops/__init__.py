"""Karthik — the operator for the Karthik Paper Wallet, and nothing else.

Karthik is an *operational layer*. He watches one wallet, records what he
finds, and hands anything ambiguous to the owner. He does not decide what that
wallet trades, when it enters, or when it exits: those are the wallet's own
rules, and every one of them is on the list in `authority.py` that he is
forbidden to touch.

── THE WALLET DOES NOT EXIST YET ────────────────────────────────────────

At the time this module was written there was no Karthik Paper Wallet in the
code or in any database, and creating one is a strategy decision reserved for
the owner. So the whole module is built to be *correct while unbound*: every
surface reports `NOT DESIGNATED` rather than zero, the integrity score is
`None` rather than 100, and no report claims a figure it could not read.

Binding it later is one environment variable — `KARTHIK_WALLET_STRATEGY_ID` —
and `wallet.py` is the only file that reads it.
"""
