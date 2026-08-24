"""Capability probe for the configured RPC chain. Redacted output only.

Run inside any backend container:
    python -m scripts.probe_rpc            # probes the router (chainstack->helius)
    python -m scripts.probe_rpc chainstack # probes one provider by name

Tests the exact standard methods MEMESCOPE's collectors and gates use, and
reports PASS/FAIL, latency, and the error class — never the endpoint or key.
"""

from __future__ import annotations

import asyncio
import sys
import time

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

PROBES = [
    ("getTokenSupply", [WSOL]),
    ("getTokenLargestAccounts", [WSOL]),
    ("getAccountInfo", [WSOL, {"encoding": "base64", "commitment": "confirmed"}]),
    ("getMultipleAccounts", [[WSOL, USDC], {"encoding": "base64"}]),
    ("getSignaturesForAddress", [USDC, {"limit": 3}]),
]


async def main() -> int:
    from app.services.rpc.registry import get_research_rpc, get_rpc

    which = sys.argv[1] if len(sys.argv) > 1 else "auto"
    rpc = get_research_rpc() if which == "auto" else get_rpc(which)
    failed = 0
    async with rpc:
        print(f"probing: {rpc.describe().endpoint}")
        for method, params in PROBES:
            started = time.perf_counter()
            try:
                result = await rpc.call(method, params, attempts=2)
                ms = int((time.perf_counter() - started) * 1000)
                provider = getattr(rpc, "last_provider", None) or which
                ok = result is not None
                print(f"  {method:<26} {'PASS' if ok else 'EMPTY':<5} {ms:>5}ms via {provider}")
                failed += 0 if ok else 1
            except Exception as exc:
                ms = int((time.perf_counter() - started) * 1000)
                print(f"  {method:<26} FAIL  {ms:>5}ms {type(exc).__name__}: {str(exc)[:90]}")
                failed += 1
            await asyncio.sleep(1.5)
    print("RESULT:", "ALL PASS" if failed == 0 else f"{failed} failures")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
