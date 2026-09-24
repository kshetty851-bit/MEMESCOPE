"""Money blocked for good: the addresses behind rug pulls that are refused
outright, each with the moment it went live.

The real wallet refuses a coin whose big wallets or their funders are on this
list (`app.real_wallet_safety.sources`), and so does the graduation lab, so a
lab book never trades a coin the wallet would not (Karthik, 2026-09-19). It
lives here, not in the wallet, because the lab may not import the wallet's
code; one list for both means the two can never drift apart.

Funders whose coins MOSTLY rugged, found by replaying BASE_75k_5m's trades
on-chain (15-18 Sep 2026), and the wallets that pulled a pool themselves. On the
trades replayed, each cost less blocked than traded. Big launch funders behind
a single rug are deliberately NOT here: ZBCN's funded 65 of the book's coins
and one rugged. Nor are exchanges and wallet-seeding services, whose coins are
anyone's. The three-hour block catches a new operator's repeats.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


#: Address -> when the wallet started refusing it. A book restated after the
#: fact applies each entry only from here, never with hindsight.
BLOCKED_SINCE: dict[str, datetime] = {
    # One operator, 16 Sep 02:08-11:38: TRUMP, POT, baton, ALLINU, Benz,
    # TikTok, ARCH, FAIR, USWS, PONYX, YouTube. It funded the curve buyer
    # (11 rugs of its 20 coins) ...
    "DyaESzDfBLtbvKz7iM5Th6nsbsGSpjt5NLXuieigRcZX": _at("2026-09-18 14:54"),
    # ... and the pool buyer (11 rugs of 19).
    "5W84xUtSNhMutNbT8XdgWrMShMgmjxjbQKK7zebdLaSn": _at("2026-09-18 14:54"),
    # The pool buyer of SUUB and SOLCAT, 18 Sep: 2 rugs of its 3 coins.
    "xZJADxiqWhDneh6wUtAfRM3gRRpj4tjw7V7ExTPXQ7z": _at("2026-09-18 14:54"),
    # The wallets that pulled the pool THEMSELVES in B3_198k_4m's two on-chain
    # rugs: each put ~99% of its pool's SOL in at launch and took 82-96% of it
    # back in one sale ~2 min after the buy.
    # ZBCN (17 Sep, -$46.38 on the wallet): its pool buyer, still launching
    # (26 of the book's 379 trades, -$11 at $25 with its dump counted), and
    # the one-shot account that funded it.
    "GBdQ1Vz6Mw2Nx5TLs61KS3GsJBwccKGj9zxZZD4FWuaK": _at("2026-09-18 19:34"),
    "6JqtR1h3QZ5BumnbKhtUXPsFaZcrRrBoi5ae3HLB8iVT": _at("2026-09-18 19:34"),
    # WWR (18 Sep, -$9.92): its pool buyer and its curve buyer, both emptied
    # since. Their funders are left out on purpose: 34nDrS holds ~2,950 SOL and
    # sends 1,000 transactions in 6 minutes (an exchange), 96UiVw seeded wallets
    # at 1,000 in 12 minutes (a service).
    "6cb6cF9EeDvjuerUR3h9zWNFL3bKmNnvnomJ24qhKUJ7": _at("2026-09-18 19:34"),
    "8EdVxQ78Y4DQJsqSmnkH1ySPGu1sqab8WAYL8mgFCt9j": _at("2026-09-18 19:34"),
    # Each of these rugs was ONE operator: its curve buyer (funded off an
    # exchange) sent ~5,000 SOL through a one-shot account to its pool buyer,
    # which filled the pool and later pulled it. ZBCN's curve buyer is that
    # operator's main wallet.
    "8eEQ6s6gNykb9sFhS5aihsxMenTTqZkm25EqNNFaDvwf": _at("2026-09-19 03:21"),
    # COST (18 Sep 21:35, -$43.24 on the wallet at $50): the pool buyer took
    # 702 of its 989 SOL back 15 s after the wallet's buy. Its curve buyer, the
    # one-shot account between them, and the pool buyer. Their other funder,
    # 5tzFki, is an exchange hot wallet (~2M SOL) and stays OFF this list.
    "2Cghr56XrPXRAJhzVRor2pSnDFYVe2t2guKgdzNSjQsT": _at("2026-09-19 03:21"),
    "wqcTmHNuzxihz8bSckYd5e7n8zBUgtLGEWhXfuoS1gv": _at("2026-09-19 03:21"),
    "EvfSd1qWRKLmCzoD66mi64fehEikgHYdJv5s67FBqtmE": _at("2026-09-19 03:21"),
    # Repeat operators among BASE_75k_5m's 31 rugs (15-19 Sep): 18 of the 30
    # traced came from three, linked by shared wallets.
    # The 16 Sep wave's pool buyers (its funders are listed above): on 8 and 3
    # of its 11 rugs.
    "E7mdTgYspRGRAE1zJoUW8zdxNU5VjpQbivXU6huB7oqJ": _at("2026-09-19 06:48"),
    "5MYVpHEiLHkddGHQhZMfhwSVqYi3yzmpmGfRxSeavBvL": _at("2026-09-19 06:48"),
    # SUUB, SOLCAT, WEN, Pump, ELIEN (18 Sep): this pool buyer bought all five
    # (xZJADx above funded it). Its curve funder, 8zxkme, stays off: ~930 SOL and
    # 1,000 transactions in half an hour looks like a service.
    "BGCbX7bcXAnbKuUP9uUfAGzQyZRz158kAzYPNKpTLCe2": _at("2026-09-19 06:48"),
    # FOMO and AMAZON (18 Sep, an hour apart): the same big wallet. Their shared
    # funder, BZXZ8d, stays off: 578 transactions in 36 minutes, a seeder.
    "DdtsVPAnET6MqDPvDumgUBsTYpYcn7UZpKMG8uwJzJyo": _at("2026-09-19 06:48"),
    # KIBA (19 Sep 07:00, -99% in every book incl. B3_198k_4m and E75T_4m): its
    # launch wallet put 1,534 SOL in (4 clean coins before, so it looked
    # proven); a new wallet funded through a one-shot account sold 28% of the
    # coins from 47 s after the buy and took 1,953 SOL. Launch wallet, dumper,
    # one-shot funder. The busy funder behind the launch wallet (4gwSSV, 272
    # coins) stays off.
    "9x2N1MHxs5NxAYnpkNi1QbyE3ayk6oqh53p9vpVjDdHa": _at("2026-09-19 09:02"),
    "FtvDtRoKP7vBPwwow1W5uttUVnXoskZ5bFnpkijb1iwL": _at("2026-09-19 09:02"),
    "3YfWwbV9QZbGfyQWHKGANdK8iwnMcpdWj1E2SqMvWkc6": _at("2026-09-19 09:02"),
    # ECTF (19 Sep 17:23, -96.7% in BASE_75k_5m's fresh $500 book): the same
    # move again. Its pool wallet put 493 SOL in at launch (560 of the pool's
    # 564 SOL at the buy) and took 472 back in one sale 4 min after the buy;
    # its launch wallet bought 79% of the coins and sold into the empty pool
    # for 106 more. Both were new, gassed off exchanges (is6MTR, 5tzFki), and
    # their money came from and went back to 34nDrS (WWR's exchange, above)
    # through one-shot accounts: all of those stay off.
    "6MzSwDcwB4PsHnLzh6gq6TmcwuogbJZH1Qg8o24xuZwK": _at("2026-09-19 18:00"),
    "7PoS8EagdxcYgKM3xz7q6tEBKGVyPUynHFFnjfvBgTr8": _at("2026-09-19 18:00"),
    # HYPED (19 Sep 18:03, -63.4% in the fresh $75k book). This one funded the
    # SUUB group and was left OFF on 19 Sep because ~930 SOL and 1,000
    # transactions in half an hour looked like a service. Its record says
    # otherwise: 186 coins, 36 of them rugged (19%), against a base rate of
    # 3-5%, and 11 trades of this book, 4 of them rugs, -$235.
    "8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg": _at("2026-09-20 08:30"),
    # The night of 21-22 Sep, both taken by the REAL wallet on G-QUIET, at
    # Karthik's request the morning after ("block rug and loss address").
    #
    # AROS (22 Sep 03:53 UTC, -100%, -$25.00 real). The pool held $365,302 at
    # the buy and $372,041 at four minutes; at five it held $404. Drained
    # inside the fifth minute. One of TEN coins called AROS this book bought
    # between 01:10 and 04:21; the other nine paid +0.8% to +5.8%. They share
    # no wallets — the one address on two of them sits on 86 coins with no
    # rugs — so the campaign used fresh money per coin and nothing here can
    # reach the next one. Each of these four sits on 1-2 coins, so blocking
    # them refuses nothing else.
    "2fX4U2QU3qtNypGzYKBEsHfQEzY7uL4kcSdzeiUDYiX9": _at("2026-09-22 05:00"),
    "72iwPTUy71ed9SfniyhBTHvSdxBcB5YS1cjArzQH3PbP": _at("2026-09-22 05:00"),
    "7RHdPkKj6zZb5A7kSvtANDiy8GSySybped3m6LYjGGan": _at("2026-09-22 05:00"),
    "AkAqdGxJRnpEWdGQGZ4N559pfY77nbZVZDsf2gAyTXfk": _at("2026-09-22 05:00"),
    # RICH (22 Sep 00:27 UTC, -66.4%, -$16.59 real). A bleed, not a drain: the
    # pool went $135,734 -> $76,981 over the five minutes, and a four-minute
    # exit would have been WORSE (-68.2%). 5QDtfF is the one with a record —
    # 18 coins, 4 rugged (22%) — and the repeat-rugger rule already refuses it
    # since the coin bar moved to 10 on 2026-09-21; it is named here so it
    # stays refused if that rule is ever loosened. The other three sit on 1-2
    # coins each.
    "2275c6uqPKnp6oUP9LbadzUCxMtTiXktogsU8QGDBaUi": _at("2026-09-22 05:00"),
    "5QDtfFdBxaUP3vT7bK5F1MHRUnkpTFW1Wj4GqCU7kk9X": _at("2026-09-22 05:00"),
    "9vCfhjuALLBfP8LuaaCYFWMVLzoxF1KpCbJdqjC5BA1X": _at("2026-09-22 05:00"),
    "wsyZWfNxvmY1a4B3sGrBSMtHCZAwUB9Fk5jbHjCS9Pk": _at("2026-09-22 05:00"),
    # EVO (24 Sep 15:41 UTC, -100%, -$25.00 real on G-QUIET), at Karthik's
    # request that evening ("block EVO funders"). A $146k pool, quiet, passing
    # every rule; it fell under half its entry price 211 seconds in, so the
    # four-minute book died too. Fresh money: none of these four was on the
    # permanent list, the wide rug-linked list or the repeat-rugger rule when
    # it was bought. Each sits on 1-3 coins, EVO the only death among them, so
    # blocking them refuses almost nothing else. Not the same money as the
    # EVO that died on 20 Sep (that one's funders were never recorded).
    "21jNtCAap2pRH3eFSP7tJ61BVYk3wXxx7XQ6XtQTnHZZ": _at("2026-09-24 15:55"),
    "6CKChsMihpXSNPn5aLYEgryhbtEQSF1dZPBGRKbsA688": _at("2026-09-24 15:55"),
    "3jih9qfEA1EmwJ3B2VUp5ouL67ezHdGyzCoE2hDSy3WA": _at("2026-09-24 15:55"),
    "9mtcjpPBiTKZQucbzXpMKLb7o237LyQy7r9W3MvXDz4M": _at("2026-09-24 15:55"),
}

ALWAYS_BLOCKED: frozenset[str] = frozenset(BLOCKED_SINCE)
