# V1.2 Progressive Profit-Lock — Frozen Research

> Research only. No wallet, position, or strategy state was written.

## Result

- Starting equity: $1,000.00
- Ending equity: $272.39
- Net P/L: $-727.61
- Return: -72.76%
- Trades opened: 50
- Trades rejected: 86
- Wins / losses: 14 / 34
- Win rate: 29.17%
- Gross profit / loss: $213.44 / $-925.98
- Profit factor: 0.23
- Expectancy: $-14.84
- Execution costs: $182.31
- Maximum drawdown: 77.95%
- Exits: fixed TP 0, initial stop 23, profit floor 25, unresolved 2
- Median winner / loser: $15.17 / $-18.99
- Largest winner / loss: $47.69 / $-99.53
- Average winner / loser: $15.25 / $-27.23

## Threshold retention

- +15%: 25 trades; average eventual retained gross return: 5.11%
- +25%: 18 trades; average eventual retained gross return: 11.56%
- +40%: 9 trades; average eventual retained gross return: 22.09%
- +60%: 5 trades; average eventual retained gross return: 25.35%
- +100%: 2 trades; average eventual retained gross return: 15.80%

## Chronological validation

### Early 60% / Late 40%

- Train: return -20.73%, PF 0.43, expectancy $-7.75, max drawdown 68.79%
- Test: return -76.50%, PF 0.06, expectancy $-27.81, max drawdown 86.11%

### Early 70% / Late 30%

- Train: return -27.15%, PF 0.46, expectancy $-7.16, max drawdown 69.15%
- Test: return -56.86%, PF 0.12, expectancy $-22.74, max drawdown 75.27%

## Versus canonical V1.1

V1.1 ending equity: $556.65; P/L: -$443.35; PF: 0.61.

### Top 15 improvements

| Mint | V1.1 net/mark | V1.2 net/mark | Difference |
|---|---:|---:|---:|
| `535ES1hrVy9SwLUkouawQeoXSkPB2zGXhTU222enbZWU` | $-100.17 | $-10.97 | $89.20 |
| `Edpcd9aYh6BVRKV5hYrgnEuJ3MHAFcdnHtSL9yvopump` | $-41.01 | $3.13 | $44.14 |
| `9dwHn2KWApoGj4MeMLVGFuqDLLWqhDRkpEGCjGmcpump` | $-43.08 | $-18.38 | $24.69 |
| `6Quog29HQ5tA5BdnCv3FWpW8WEpdxCsxEpt2TGCZpump` | $-27.70 | $-3.74 | $23.95 |
| `ANWSnRAdxuzsReerVCHSVLzYoFn8P4husnfufBBxpump` | $-36.07 | $-17.94 | $18.13 |
| `Gymbmn9wwMKe4NnmVceyyfpncp9arbwPfSdBsyY9pump` | $-26.41 | $-11.35 | $15.06 |
| `EJFseq4RFonjh9u6bzYLFynJin9WLKHF7jCgVoSXpump` | $-32.38 | $-17.74 | $14.64 |
| `EeB76LHyVZPMRvTpLcxJqqfSz4gg9f9XgsUmFybcpump` | $-29.21 | $-16.55 | $12.66 |
| `2sQ7wuUtRWNir3CEu9HWfLDSut4AszDrcZXLobzJpump` | $35.18 | $47.69 | $12.51 |
| `HB7MPRYpegrJaJtsZvrXAEHx5kxdehiQQUNneVLnpump` | $-27.73 | $-17.06 | $10.67 |
| `7WmG1z9ysDhAWY7vCGkbhAG3zCaVUzzZrEAUj1hjpump` | $-29.42 | $-19.49 | $9.93 |
| `7hmVkPXmVagxoptAEpx4jBzZVHwGLdFj6c1y42qxpump` | $-26.97 | $-17.24 | $9.73 |
| `D6D86WfHuviN4Sra4uvMGHkedtEHCC893krgntGjpump` | $-31.46 | $-22.04 | $9.43 |
| `GTQ9LhnDbyRE3MFQA3LzF7fY1MMe4S4NMQWpkUcspump` | $-26.01 | $-16.77 | $9.24 |
| `Aq2idw7BeJX2WfNek6jGnp1z2s79CpFYZXo2zCF1pump` | $-31.61 | $-24.11 | $7.50 |

### Top 15 deteriorations

| Mint | V1.1 net/mark | V1.2 net/mark | Difference |
|---|---:|---:|---:|
| `3VFnDoACa991DYe987w354sbvmhqjjzC4Z31SoZepump` | $32.68 | $-25.43 | $-58.11 |
| `3e53B7z3kkWcp9NrpJsRC5e5U6sNwxbHXmAXBH5tpump` | $41.00 | $-17.04 | $-58.04 |
| `5mPVUc7pDVZnJx28vrZFwYQcsMqqWsoW3QWdNTmZpump` | $81.54 | $26.51 | $-55.04 |
| `DxnPojFH2FfeEqwq6DhBhEFEyvrgbeTNZ3tSUW3rpump` | $29.39 | $-20.29 | $-49.68 |
| `9imhB1nbwRQ2c6Cf6Zz6zUdjPjNsWBatpug1ZtxibEWz` | $29.86 | $-18.77 | $-48.63 |
| `Ef4E8vBoosFWhxXWqRHQAsXiuuAbocrN9PnpgHNrpump` | $26.95 | $-4.98 | $-31.93 |
| `2tBjFsno9tdkX7AhZ9uehAet5o8GninkrqDYZZYUpump` | $33.28 | $1.38 | $-31.90 |
| `kpmhzGSYni1ta6Crc1xRDne2g7NTuEmmNJpDxwvpump` | $31.90 | $0.68 | $-31.22 |
| `AaXXFmEtfowS9fMomUibZoxmz8sZSmUgxG6By3Sepump` | $14.41 | $-14.42 | $-28.83 |
| `8KomtC3jBZiW1g791pnHVxcNyX5JhTPMKJpsv232dPcy` | $40.89 | $13.11 | $-27.78 |
| `7C17GMDWxy2wCggRXEKKeTY21B84mT9vv9c6b1vTpump` | $27.03 | $0.67 | $-26.36 |
| `DHKfiAzT1uhMXdLZyHzbPU1TmVX7jgR4rkeYcQq3pump` | $26.00 | $2.85 | $-23.15 |
| `2YxEmTED9G5ZpxwfBHuVzPVQ4TfMYTAjMo5Tx1WApump` | $30.35 | $7.24 | $-23.11 |
| `8T3suJtKUGrWRytVNKe7RLV81AumvmBPQfEkyeHtpump` | $42.54 | $28.27 | $-14.26 |
| `A13oRB9FFaiUjfi6LdCg6p9ka1u8SfGkUFs4SKvPpump` | $32.76 | $18.74 | $-14.02 |
