"""Clone-risk routes.

The only API addition in Phase 12, and it exists because the UI cannot compute
this: deciding whether a name is contested needs a scan across every discovered
token, which is a database question, and banding the answer is a verdict — both
of which belong on this side of the wire.

Batched deliberately. The home page shows several sections of several tokens
each, and a per-token lookup would turn one screen into dozens of requests.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path

from app.api.deps import DbSession
from app.repositories.token import TokenRepository
from app.schemas.identity import IdentityOut, IdentityPage
from app.services import identity

router = APIRouter(prefix="/identity", tags=["identity"])

MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

#: Bounded so one request cannot ask for a scan of the whole table.
MAX_BATCH = 100


def _to_out(mint: str, assessment: identity.IdentityAssessment) -> IdentityOut:
    return IdentityOut(
        mint_address=mint,
        sharing_name=assessment.sharing_name,
        discovered_before=assessment.discovered_before,
        is_earliest_known=assessment.is_earliest_known,
        clone_risk=assessment.clone_risk.value,
        identity_confidence=assessment.identity_confidence.value,
        explanation=assessment.explanation,
    )


@router.post(
    "/batch",
    response_model=IdentityPage,
    summary="Clone risk for several tokens at once",
)
async def assess_batch(
    session: DbSession,
    mint_addresses: Annotated[list[str], Body(embed=True, max_length=MAX_BATCH)],
) -> IdentityPage:
    """Clone risk per mint.

    A mint the scanner has never seen, or one with no recorded name, comes back
    with the unnamed assessment rather than being omitted — a caller must be
    able to tell "checked, nothing to compare" from "not checked".
    """
    collisions = await TokenRepository(session).name_collisions(mint_addresses)

    items = []
    for mint in dict.fromkeys(mint_addresses):
        found = collisions.get(mint)
        assessment = (
            identity.assess(sharing_name=found[0], discovered_before=found[1])
            if found is not None
            else identity.unnamed()
        )
        items.append(_to_out(mint, assessment))

    return IdentityPage(items=items)


@router.get(
    "/{mint}",
    response_model=IdentityOut,
    summary="Clone risk for one token",
)
async def assess_one(
    session: DbSession,
    mint: Annotated[str, Path(pattern=MINT_PATTERN)],
) -> IdentityOut:
    collisions = await TokenRepository(session).name_collisions([mint])
    found = collisions.get(mint)
    assessment = (
        identity.assess(sharing_name=found[0], discovered_before=found[1])
        if found is not None
        else identity.unnamed()
    )
    return _to_out(mint, assessment)
