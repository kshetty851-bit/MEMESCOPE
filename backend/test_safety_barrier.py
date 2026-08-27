import asyncio
from app.services.rpc.standard import StandardSolanaRPC
from app.real_wallet.network import require_verified_devnet, DevnetExecutionBlockedError

async def main():
    print("Connecting to local solana-test-validator...")
    rpc = StandardSolanaRPC(rpc_url="http://127.0.0.1:8899")
    try:
        async with rpc:
            await require_verified_devnet(rpc, configured_network="devnet")
        print("FAIL: Barrier did not block execution. It somehow verified devnet!")
        exit(1)
    except DevnetExecutionBlockedError as e:
        print(f"SUCCESS: Safety Barrier blocked execution as expected! Reason: {e}")
        exit(0)
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
