"""Who funded a wallet: the account that paid the most SOL into it, the first
time anything did."""

from __future__ import annotations

from app.real_wallet_safety import sources


def _tx(balances: dict[str, tuple[int, int]]) -> dict:
    keys = list(balances)
    return {"transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys]}},
            "meta": {"preBalances": [balances[k][0] for k in keys],
                     "postBalances": [balances[k][1] for k in keys]}}


class _History:
    """A wallet's oldest transactions, served a page at a time."""

    def __init__(self, pages: list[list[dict]]) -> None:
        self.pages, self.asked = pages, []

    async def call(self, method: str, params: list) -> dict:
        assert method == "getTransactionsForAddress"
        assert params[1]["sortOrder"] == "asc", "a funder is found at the START of a history"
        n = len(self.asked)
        self.asked.append(params[1].get("paginationToken"))
        more = n + 1 < len(self.pages)
        return {"data": self.pages[n], "paginationToken": f"p{n + 1}" if more else None}


async def test_the_funder_is_who_paid_the_most_the_first_time_the_wallet_was_paid() -> None:
    history = _History([[
        # Rent for the wallet's token account, paid BY the wallet: not a funding.
        _tx({"Wallet": (5_000_000, 2_960_000), "Rent": (0, 2_039_280)}),
        # The funding: a relayer pays the fee, the operator pays the SOL.
        _tx({"Relayer": (1_000_000, 995_000), "Operator": (50_000_000_000, 25_000_000_000),
             "Wallet": (2_960_000, 25_002_960_000)}),
        _tx({"Later": (9_000_000_000, 1_000_000_000), "Wallet": (0, 8_000_000_000)}),
    ]])
    assert await sources.funder(history, "Wallet") == "Operator"


async def test_the_search_turns_the_page_and_stops_after_two() -> None:
    idle = [_tx({"Wallet": (10, 5), "Fee": (0, 5)})]
    history = _History([idle, [_tx({"Operator": (10, 0), "Wallet": (0, 10)})]])
    assert await sources.funder(history, "Wallet") == "Operator"
    assert history.asked == [None, "p1"]

    deep = _History([idle, idle, [_tx({"Operator": (10, 0), "Wallet": (0, 10)})]])
    assert await sources.funder(deep, "Wallet") is None
    assert len(deep.asked) == sources.FUNDING_PAGES


async def test_trace_keeps_the_wallets_and_drops_the_untraceable_funders() -> None:
    class Chain:
        async def call(self, method: str, params: list) -> dict:
            if params[0] == "Traced":
                return {"data": [_tx({"Operator": (10, 0), "Traced": (0, 10)})]}
            return {"data": []}

    found = await sources.trace(Chain(), ["Traced", "Silent"])
    assert found == sources.Sources(wallets=("Traced", "Silent"), funders=("Operator",))
    assert found.ids() == {"Traced", "Silent", "Operator"}
