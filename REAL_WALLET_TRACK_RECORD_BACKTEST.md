# MEMESCOPE Track Record Exit-Strategy Backtest

**Analysis-only report — no scanner, Radar scoring, paper-trading, or real-wallet execution logic was changed.**

- Dataset queried: **392** immutable Track Record detections, from **2026-07-29 07:54 UTC** through **2026-08-15 17:36 UTC**.
- Historical source: `radar_tokens.first_detected_at/first_market_cap` for entry and append-only `token_market_snapshots` for post-detection market-cap observations.
- Latest post-detection observation used in this run: **2026-08-15 18:13 UTC**.
- Starting bankroll: **$1,000**.

## Method and data quality

Each entry is the token's frozen, actual MEMESCOPE detected market cap. For each strategy, I scanned the post-detection point samples in timestamp order and assigned the first sample at or above TP, or at or below the 0.75× stop. A confirmed exit is filled at its threshold (TP or stop), not at a later, overshot sample price.

The finest stored historical resolution is an **irregular timestamped point series** — no OHLC high/low candles. Across the Track Record mints, the database contained 6,909,858 market snapshots; all 392 tokens had post-detection history (median 1,376.5 samples/token). Per-mint inter-snapshot gaps had a 40.5-second median, 15.6-second p10, and roughly 61-minute p90. The data cannot prove movements between samples, so this report does not infer them.

A scalar point cannot be simultaneously both the upper TP and lower stop. There were no duplicate mint/timestamp samples, so **ambiguous count is zero** for every strategy. If a future source supplies an OHLC bar that crosses both thresholds without an ordering signal, it must be classified **AMBIGUOUS** and shown as both optimistic/conservative — it is not guessed here.

Open trades have not reached either threshold in the observed data. They are excluded from sequential “completed trade” compounding and are marked at their final observed sample only in the equal-dollar comparison.

## Important portfolio-capacity warning

All **392/392 tokens** overlap at least one other Track Record interval, producing **8,924 overlapping interval pairs**. A literal “100% bankroll for every chronological detection” cannot execute all 392 positions. The serial all-in results below are therefore an order-dependent stress test, not an executable portfolio. As a sanity check, a time-feasible 1.5×/0.75× all-in schedule could take only **18** detections and had to skip **374** because capital was already tied up; it ended at **$641.45 gross** (6 TP, 10 SL, 2 open).

## Gross results — no fees or slippage

| TP | TP / SL / Open | Win rate | Average closed return | 100% sequential final | 100% max DD | 10% current-bankroll final | 10% max DD | Equal-$ final |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.25× | 179 / 180 / 33 | 49.86% | -0.07% | $0.01 (-100.00%) | 100.00% | $871.77 (-12.82%) | 42.49% | $994.18 (-0.58%) |
| 1.5× | 119 / 232 / 41 | 33.90% | 0.43% | $0.00 (-100.00%) | 100.00% | $934.54 (-6.55%) | 44.94% | $1,000.91 (0.09%) |
| 1.75× | 90 / 259 / 43 | 25.79% | 0.79% | $0.00 (-100.00%) | 100.00% | $952.70 (-4.73%) | 54.57% | $1,005.03 (0.50%) |
| 2× | 69 / 276 / 47 | 20.00% | 0.00% | $0.00 (-100.00%) | 100.00% | $662.78 (-33.72%) | 61.11% | $1,003.70 (0.37%) |
| 2.5× | 52 / 290 / 50 | 15.20% | 1.61% | $0.00 (-100.00%) | 100.00% | $928.17 (-7.18%) | 61.12% | $1,016.58 (1.66%) |
| 3× | 36 / 305 / 51 | 10.56% | -1.25% | $0.00 (-100.00%) | 100.00% | $314.00 (-68.60%) | 82.99% | $994.02 (-0.60%) |

The 100% serial curve finishes effectively at zero for every TP setting because it forces hundreds of completed, overlapping trades into one sequential bankroll. It is shown because requested, but it should not guide deployment.

For fixed 10% sizing, **1.75×** is the least-bad gross risk-adjusted result: **$952.70** final (-4.73%), 54.57% maximum drawdown, profit factor 1.04. Its return-to-drawdown ratio is -0.087; all settings still lost money in this path. The gross equal-dollar comparison, which avoids arbitrary serial ordering, is highest at **2.5×: $1,016.58 (+1.66%)**.

## Configured-cost results

The configured MEMESCOPE cost model is `app/paper/costs.py`: **30 bps protocol fee per side** plus constant-product price impact against half of the observed reported liquidity at entry and exit. It intentionally excludes competing-flow slippage, priority-fee competition, MEV, and bonding-curve impact because the snapshot data cannot support them. A configured priority fee exists, but no contemporaneous SOL/USD series is stored, so it is not fabricated into this backtest.

| TP | 100% sequential, configured costs | 10% current-bankroll, configured costs | Equal-$, configured costs |
|---:|---:|---:|---:|
| 1.25× | **Bankrupt / invalid at trade 8** | $294.18 (-70.58%); DD 74.91%, PF 0.79 | $986.83 (-1.32%); PF 0.89 |
| 1.5× | **Bankrupt / invalid at trade 3** | $318.57 (-68.14%); DD 73.14%, PF 0.86 | $993.43 (-0.66%); PF 0.96 |
| 1.75× | **Bankrupt / invalid at trade 3** | $289.43 (-71.06%); DD 79.28%, PF 0.88 | $997.46 (-0.25%); PF 0.99 |
| 2× | **Bankrupt / invalid at trade 3** | $202.46 (-79.75%); DD 85.83%, PF 0.85 | $996.09 (-0.39%); PF 0.98 |
| 2.5× | **Bankrupt / invalid at trade 1** | $245.34 (-75.47%); DD 83.18%, PF 0.91 | $1,008.88 (0.89%); PF 1.04 |
| 3× | **Bankrupt / invalid at trade 1** | $115.96 (-88.40%); DD 92.69%, PF 0.83 | $986.34 (-1.37%); PF 0.93 |

The linearized constant-product cost model becomes physically invalid for the unconstrained all-in curve once its order size exceeds available pool depth (net proceeds would turn negative). I stop and label that as bankrupt/model-invalid rather than allowing a negative account to compound. This is a concrete reason the 100% version is not executable.

With costs, the best fixed-10% setting is **1.5×**, but it still ends at **$318.57 (-68.14%)**. The equal-dollar result remains highest at **2.5×: $1,008.88 (+0.89%)**. That small positive number is not an execution-ready claim: it excludes the unmodelled costs listed above and assumes every position can be opened simultaneously.

## Requested base strategy: 1.5× TP / 0.75× SL

- Tokens analyzed: **392**
- Take profits: **119**
- Stop losses: **232**
- Open/unresolved: **41**
- Ambiguous: **0**
- Closed-trade win rate / loss rate: **33.90% / 66.10%**
- Average closed return: **+0.43%**
- Gross 100% sequential final / P&L / total return: **$0.00 / -$1,000.00 / -100.00%**
- Gross 100% maximum drawdown / longest losing streak / profit factor: **100.00% / 10 / 1.03**
- Gross fixed-10% final / P&L / total return: **$934.54 / -$65.46 / -6.55%**
- Gross fixed-10% maximum drawdown / longest losing streak / profit factor: **44.94% / 10 / 1.03**
- Gross equal-$ final / P&L / total return: **$1,000.91 / +$0.91 / +0.09%**
- Configured-cost fixed-10% final / P&L / total return: **$318.57 / -$681.43 / -68.14%**
- Configured-cost equal-$ final / P&L / total return: **$993.43 / -$6.57 / -0.66%**

## Recommendation

**Do not treat 1.5× TP / 25% SL as supported for live deployment from this Track Record.** It has a modestly positive average gross closed-trade return and PF 1.03, but only a 33.9% win rate, a 10-loss streak, a -6.55% gross fixed-10% compounded result, and a -68.14% configured-cost fixed-10% result. Its tiny +0.09% equal-dollar gross gain becomes -0.66% once the existing model’s fees and impact are applied.

**2.5× / 25% SL produced the highest terminal value in the less order-distorted equal-dollar comparison** (+1.66% gross, +0.89% under configured costs). **1.75× / 25% SL was the least-bad gross risk-adjusted fixed-10% setting**, but still lost money. No tested combination clears a robust historical support threshold after configured costs. Before any production exit change, improve executable capacity constraints and collect execution-quality data (especially bonding-curve depth, fills, priority fees, and competing-flow slippage).

## Per-token audit — 1.5× TP / 0.75× SL, gross

The table below contains one row per Track Record token. “High” and “Low” are the observed **strictly post-detection** sample multiples; no intraperiod path is invented. “Bankroll” columns are the requested naïve 100%-serial gross ledger: resolved trades update the balance in detection-time order; OPEN rows are unsettled and do not reserve capital, which is exactly why this ledger is not deployable given the overlap warning.

| # | Mint | Detected (UTC) | Entry MC | High × | Low × | TP hit | SL hit | First threshold | Exit reason | Return | Bankroll before | P/L | Bankroll after |
|---:|---|---|---:|---:|---:|:---:|:---:|---|---|---:|---:|---:|---:|
| 1 | FWAz11UtkMpSVs7eFFzVZKxwK7CjjM92RLpzVpmUPUMP | 2026-07-29 07:54:28.472329 | $22,306,767.00 | 2.104× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1,000.00 | $500.00 | $1,500.00 |
| 2 | 6Quog29HQ5tA5BdnCv3FWpW8WEpdxCsxEpt2TGCZpump | 2026-07-29 07:54:41.583766 | $225,974.00 | 2.635× | 0.047× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1,500.00 | $750.00 | $2,250.00 |
| 3 | Bk51awBXWkRsNzSEdcz46AMFANwtaJy2chuaptNpump | 2026-07-29 07:54:41.583766 | $389,989.00 | 1.361× | 0.004× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2,250.00 | $-562.50 | $1,687.50 |
| 4 | GTQ9LhnDbyRE3MFQA3LzF7fY1MMe4S4NMQWpkUcspump | 2026-07-29 07:54:41.583766 | $43,029.00 | 22.297× | 0.961× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1,687.50 | $843.75 | $2,531.25 |
| 5 | SWFuUxA6TkRhXomCh8fUJ7KbbyXmt7GJLAPKj1kpump | 2026-07-29 07:54:41.583766 | $184,480.00 | 1.475× | 0.008× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2,531.25 | $-632.81 | $1,898.44 |
| 6 | uJ6HKAuLnrt4jgUxHKXRp8jCtk9ap51FwBKtQkupump | 2026-07-29 07:54:41.583766 | $248,067.00 | 3.458× | 0.006× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1,898.44 | $949.22 | $2,847.66 |
| 7 | qcjNtNLjz46MnRTt8wA7xPBUeXtX3WhizGMcCGtpump | 2026-07-29 08:01:50.827973 | $1,945,218.00 | 1.366× | 0.017× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2,847.66 | $-711.91 | $2,135.74 |
| 8 | 3RXHESRfPxu5y72D5cQUDjcyzmNXJbG2fCNyjCnspump | 2026-07-29 08:15:00.038400 | $9,986,864.00 | 0.000× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2,135.74 | $-533.94 | $1,601.81 |
| 9 | 56mZroRW36NLc8evXE1EicVdmCg1Ss9UsB36R2wEpump | 2026-07-29 09:15:00.026621 | $129,429.00 | 3.301× | 0.012× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1,601.81 | $800.90 | $2,402.71 |
| 10 | 7RqsAmXi1m1z4a5EVjtbAsiYPKyMuD9aYoM5GbtKpump | 2026-07-29 09:15:00.026621 | $10,854,426.00 | 0.000× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2,402.71 | $-600.68 | $1,802.03 |
| 11 | DgH6wj5QnkGEEkMJnovXj2jbeYnuDizzUNcisHWnpump | 2026-07-29 09:15:00.026621 | $87,599.00 | 1.175× | 0.017× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1,802.03 | $-450.51 | $1,351.52 |
| 12 | g6N1TXZtTmdzzE4DCikcnpGKKcqvhHfe3ntoBHepump | 2026-07-29 09:15:00.026621 | $19,388,301.00 | 1.130× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1,351.52 | $-337.88 | $1,013.64 |
| 13 | 9R8p9D9K6BT9ud8RoDz3Va6yJ1kuFyksL6RThrhpump | 2026-07-29 09:30:00.173354 | $134,017.00 | 1.255× | 0.011× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1,013.64 | $-253.41 | $760.23 |
| 14 | 8VHwhUQeknYXMYGNP9zbWPZ5iFQpyYKdQnN1H7xSpump | 2026-07-29 09:45:00.022711 | $41,641.00 | 1.382× | 0.033× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $760.23 | $-190.06 | $570.17 |
| 15 | 8d41afFvSCVChcqUKhuNuU5uBLMd8vvrw5zRxpjVpump | 2026-07-29 09:45:00.022711 | $48,541.00 | 1.195× | 0.030× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $570.17 | $-142.54 | $427.63 |
| 16 | 9u7tQ3VJYpCzUNh3d697ALxSH1e4yCDSP7fX4eeCPump | 2026-07-29 09:45:00.022711 | $17,011,092.00 | 1.163× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $427.63 | $-106.91 | $320.72 |
| 17 | CNW3jzgCvKqiViyu59chfinwnqcWzCHCDYH2CktZpump | 2026-07-29 10:00:00.049782 | $38,583.00 | 1.047× | 0.036× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $320.72 | $-80.18 | $240.54 |
| 18 | SjUsxV1DNsAPPJuHCQJE6Qq2j69sPaGnv8rvvr9pump | 2026-07-29 10:00:00.049782 | $1,712,075.00 | 2.266× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $240.54 | $120.27 | $360.81 |
| 19 | WEx9k5yWU4DJSciHxQV55gZgHLh6me2N5Kdw2wSpump | 2026-07-29 10:00:00.049782 | $690,202.00 | 2.687× | 0.002× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $360.81 | $180.41 | $541.22 |
| 20 | 79xAcXoajNSuhGsFHZB93sMBALtoPF2xqeSaHHPVpump | 2026-07-29 10:15:00.046444 | $39,842.00 | 4.174× | 0.046× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $541.22 | $270.61 | $811.83 |
| 21 | 5nutPbcoG2o9eHU4EQ7163pyQZnevcKw9qXRtR3epump | 2026-07-29 12:35:13.713287 | $20,804.00 | 1.415× | 0.079× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $811.83 | $-202.96 | $608.87 |
| 22 | 8rBqosLkDPURubFkUDX7VRFTYH6xymnfECio3mKQpump | 2026-07-29 12:35:13.713287 | $25,747.00 | 1.012× | 0.053× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $608.87 | $-152.22 | $456.65 |
| 23 | CXqMrQV4gQFp3FEkvrbJrNLKTdHrX8x5hvoZJjUmpump | 2026-07-29 12:35:13.713287 | $105,717.00 | 1.851× | 0.031× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $456.65 | $228.33 | $684.98 |
| 24 | X6R1QXdfMXSsKTq4KfBkJdTgeDvoEtn1LNT7XXmpump | 2026-07-29 12:35:13.713287 | $2,642,187.00 | 2.038× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $684.98 | $342.49 | $1,027.47 |
| 25 | hahkQzibVcMhmSdk2EoMzNBUCocKThWv8zq7Cmopump | 2026-07-29 12:35:13.713287 | $47,711.00 | 1.729× | 0.028× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1,027.47 | $513.74 | $1,541.21 |
| 26 | KdkM5tU9ymzfA3TcevVeWGggDrCxxZWA1f8FX7Jpump | 2026-07-29 13:30:00.138928 | $21,614,587.00 | 1.022× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1,541.21 | $-385.30 | $1,155.91 |
| 27 | 7cK8eRDq5RRgJewz91uJej6vjW35eu8Hiwu9qDFepump | 2026-07-29 14:00:00.022875 | $14,243.00 | 1.044× | 0.113× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1,155.91 | $-288.98 | $866.93 |
| 28 | VqmABNboP7rM7NGNBDsgX3DvdQJqpa8K9toeTCDpump | 2026-07-29 14:50:24.736490 | $138,131.00 | 4.913× | 0.013× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $866.93 | $433.47 | $1,300.40 |
| 29 | 5exGpveFdn2Dcr9o7Pyj35DoYj588rEfkNLcZqHxpump | 2026-07-29 15:04:41.861529 | $79,343.00 | 5.773× | 0.039× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1,300.40 | $-325.10 | $975.30 |
| 30 | 3VFnDoACa991DYe987w354sbvmhqjjzC4Z31SoZepump | 2026-07-29 15:15:00.035038 | $1,515,716.00 | 1.178× | 0.016× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $975.30 | $-243.82 | $731.47 |
| 31 | 6oyeKoNx3iNAiGH8apY5GPUBJDado6o5DGibNgidpump | 2026-07-29 17:19:24.155080 | $29,181.00 | 1.128× | 0.050× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $731.47 | $-182.87 | $548.60 |
| 32 | t7yA9bdb5hWrbjt1NVtsUBtwGozUcCr92XPi4DRpump | 2026-07-29 17:47:20.917503 | $1,098,872.00 | 1.140× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $548.60 | $-137.15 | $411.45 |
| 33 | 6qcsmfRrEDwhhg81oxqwELvwWoniE8kJUUeTFEZzpump | 2026-07-29 18:00:00.050499 | $24,510.00 | 1.462× | 0.068× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $411.45 | $-102.86 | $308.59 |
| 34 | 3WBWiphw1qAS2mvLttsj6Y8YjmRwZm5sshFi3EgDpump | 2026-07-30 07:30:00.040717 | $2,700,390.00 | 1.017× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $308.59 | $-77.15 | $231.44 |
| 35 | 4JBjn9nN6fXadz8aaUjHjNtn5QCkphHZ4Anyg5j6pump | 2026-07-30 07:30:00.040717 | $25,689.00 | 1.020× | 0.100× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $231.44 | $-57.86 | $173.58 |
| 36 | 7AhXcxhEeR7HuqG5XxN4PescwsBiD3rGbKUgnxeApump | 2026-07-30 07:30:00.040717 | $39,980.00 | 1.710× | 0.066× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $173.58 | $86.79 | $260.37 |
| 37 | HB7MPRYpegrJaJtsZvrXAEHx5kxdehiQQUNneVLnpump | 2026-07-30 07:30:00.040717 | $115,583.00 | 1.075× | 0.355× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $260.37 | $-65.09 | $195.28 |
| 38 | AYMEVkbSowkh72UVQTvBkdCvhDnm3eqdkGFArYdweSWA | 2026-07-30 09:12:49.311089 | $15,103.00 | 1.236× | 0.132× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $195.28 | $-48.82 | $146.46 |
| 39 | 6C5sH42znw7tHmUiNuykULuqcLDbhTWGonygNmxgpump | 2026-07-30 16:13:08.756524 | $29,658.00 | 0.219× | 0.065× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $146.46 | $-36.61 | $109.84 |
| 40 | DQH3yCBEueA97bCnKMz9c4bKyDH5tQR9bFBA1rzUpump | 2026-07-31 13:49:09.643873 | $4,064.00 | 0.915× | 0.427× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $109.84 | $-27.46 | $82.38 |
| 41 | 5mPVUc7pDVZnJx28vrZFwYQcsMqqWsoW3QWdNTmZpump | 2026-08-02 17:15:00.014004 | $30,978.00 | 3.697× | 0.472× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $82.38 | $41.19 | $123.58 |
| 42 | 2YxEmTED9G5ZpxwfBHuVzPVQ4TfMYTAjMo5Tx1WApump | 2026-08-03 19:15:03.963008 | $715,833.00 | 1.052× | 0.014× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $123.58 | $-30.89 | $92.68 |
| 43 | Gymbmn9wwMKe4NnmVceyyfpncp9arbwPfSdBsyY9pump | 2026-08-03 19:30:00.043133 | $121,582.00 | 52.322× | 0.993× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $92.68 | $46.34 | $139.02 |
| 44 | dY9TrCx431wFLvXnu2XkLvn9c6SV7MRNoxiwumJpump | 2026-08-03 19:45:00.022030 | $51,875,301.00 | 1.082× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $139.02 | $-34.76 | $104.27 |
| 45 | ELeiehuYMuxaw9skiSnLe96PK2ExY2hrDmXY7ojmpump | 2026-08-03 21:55:25.171181 | $44,781.00 | 1.426× | 0.036× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $104.27 | $-26.07 | $78.20 |
| 46 | yJTYDwcqBPZ8pQ3RPwCqEV77TTVEyMYdYngabKtpump | 2026-08-04 03:30:00.027793 | $50,429,894.00 | 1.012× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $78.20 | $-19.55 | $58.65 |
| 47 | 89RAitwPJBEfLK4Gcg5iv7AjFABHWNvoD5rkvRkvpump | 2026-08-04 03:45:00.033550 | $101,754.00 | 34.673× | 0.241× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $58.65 | $29.33 | $87.98 |
| 48 | AeabVqYgVhbXAJrjjWdUGS88hBva2wPHi3vuzFvGpump | 2026-08-04 03:45:00.033550 | $64,341,684.00 | 1.359× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $87.98 | $-21.99 | $65.98 |
| 49 | ZxBMjSMZhmGnD4WKjDKAaLhHga4u2YPsvEibuYRpump | 2026-08-04 03:45:00.033550 | $11,275,505.00 | 1.156× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $65.98 | $-16.50 | $49.49 |
| 50 | nbAZKP8rjxbGBa7uoxqgqxivfJCuY7yNL1PbPa8pump | 2026-08-04 03:45:00.033550 | $1,121,163.00 | 2.393× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $49.49 | $24.74 | $74.23 |
| 51 | 2yjK6azDS8kWj9o3UbGELydiqzmeudYFhBM4wHVEpump | 2026-08-04 04:00:00.029558 | $79,939,249.00 | 1.080× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $74.23 | $-18.56 | $55.67 |
| 52 | 9QQZZxFwj8sRgSmBKtzFLsUZD2qMvCVzg3EEWCZCpump | 2026-08-04 04:00:00.029558 | $105,091.00 | 1.355× | 0.014× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $55.67 | $-13.92 | $41.75 |
| 53 | 9zHfYVaxyP8JxR4Z4xu5esnxNwGrPTAjTWc2AUarpump | 2026-08-04 04:00:00.029558 | $133,084.00 | 1.193× | 0.011× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $41.75 | $-10.44 | $31.32 |
| 54 | t1kbmfZ83UHmSk48meiguKhcCmYgBQHksXBgnBkpump | 2026-08-04 04:00:00.029558 | $46,031,317.00 | 1.040× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $31.32 | $-7.83 | $23.49 |
| 55 | 6Hdq7xZUCKoRxXMbzKhL6WMmpbgS1y1FdpU1mzU2pump | 2026-08-04 04:15:00.094928 | $49,920.00 | 2.251× | 0.045× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $23.49 | $11.74 | $35.23 |
| 56 | ALb8gStNC3PoQeRZhiSQwgymCFMFf9Jc4RPhGuw1pump | 2026-08-04 04:15:00.094928 | $4,344,303.00 | 1.455× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $35.23 | $-8.81 | $26.42 |
| 57 | pMYacJnCRV6QfFt9nrbvaCSTnrsmtKPSCxgn4x8pump | 2026-08-04 04:15:00.094928 | $822,008.00 | 1.112× | 0.039× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $26.42 | $-6.61 | $19.82 |
| 58 | BKTB66kLi8iiXhTTFmEbVNuTv87diJiWYp4dpB3Zpump | 2026-08-04 06:30:00.023216 | $37,687,411.00 | 1.194× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $19.82 | $-4.95 | $14.86 |
| 59 | E14Zh2nA8GTwAXh5XSbz6XuVkEeDZDmx9ANibUvapump | 2026-08-04 06:30:00.023216 | $101,840.00 | 2.348× | 0.044× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $14.86 | $-3.72 | $11.15 |
| 60 | 3dPRz3igaqxkrFMWwARmAwdMTqV8WbQDVn2mkgTgpump | 2026-08-04 06:45:00.017660 | $964,178.00 | 1.870× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $11.15 | $5.57 | $16.72 |
| 61 | CBizGmyJadqExwxWpdSMUtfusSFv6K2BPHpiaac1pump | 2026-08-04 06:45:00.017660 | $5,080,937.00 | 1.010× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $16.72 | $-4.18 | $12.54 |
| 62 | m64RqWxy6GkaLzosM9bFRhKimYK2Z7DVY6VJFbrpump | 2026-08-04 07:30:00.030832 | $399,691.00 | 1.325× | 0.003× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $12.54 | $-3.14 | $9.41 |
| 63 | 2mympowvyhBW9XEDKDWWfFWDs8yCHbqqUknvGsntpump | 2026-08-04 07:45:00.127050 | $72,704.00 | 1.401× | 0.020× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $9.41 | $-2.35 | $7.05 |
| 64 | 8KomtC3jBZiW1g791pnHVxcNyX5JhTPMKJpsv232dPcy | 2026-08-04 08:00:00.042433 | $1,962,644.00 | 1.830× | 0.001× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $7.05 | $-1.76 | $5.29 |
| 65 | FnDxikf7zZj4zfjf7yMoiwV3LhN4vUzuZuUcE99pump | 2026-08-04 08:00:00.042433 | $41,263,164.00 | 7.145× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $5.29 | $2.65 | $7.94 |
| 66 | BTSiMjhntLH9NAoHC3JD5Qz8eHboJiqVpTmNyUfkpump | 2026-08-04 08:15:00.079755 | $38,203.00 | 1.031× | 0.047× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $7.94 | $-1.98 | $5.95 |
| 67 | CUYMG3SR4fscGkYrnre5A4bZpsmr9Y8kfJvuRKV4pump | 2026-08-04 08:15:00.079755 | $85,714.00 | 1.547× | 0.016× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $5.95 | $2.98 | $8.93 |
| 68 | ERyDcPn6CAzUvLF1y5kpvzDrEbo9F73QTorm5S8Apump | 2026-08-04 08:15:00.079755 | $2,304,179.00 | 1.109× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $8.93 | $-2.23 | $6.70 |
| 69 | 6GJx9vomH6pXAC9Acciz2tMz1MoAZcMPHhAQGyCCpump | 2026-08-04 09:45:00.050104 | $91,881.00 | 0.558× | 0.016× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $6.70 | $-1.67 | $5.02 |
| 70 | D3MmqB1YgTJZAta8mbWNqw2b4mjDT5KEZ71Q6kcTpump | 2026-08-04 10:00:00.025372 | $111,842.00 | 3.048× | 0.014× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $5.02 | $2.51 | $7.53 |
| 71 | ftqt1ZJA3VqopX4tjSWwCA8abDSSBAjLCDh2K2hpump | 2026-08-04 10:00:00.025372 | $369,697.00 | 1.131× | 0.004× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $7.53 | $-1.88 | $5.65 |
| 72 | Fx3QFybYmJz1qBu8Qp7FYRCGntGt8dK5Kkz9sm9Npump | 2026-08-04 10:15:00.089440 | $106,787.00 | 2.676× | 0.015× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $5.65 | $2.82 | $8.47 |
| 73 | J5NVZjRdPBNWQi4aLz6jyouxyznc7nZpJVBhJCiHpump | 2026-08-04 10:30:00.037537 | $15,780.00 | 0.097× | 0.090× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $8.47 | $-2.12 | $6.36 |
| 74 | dDqcg6kAfrJ39D3uKDRaRaAugbZav5efevKPCnmpump | 2026-08-04 10:30:00.037537 | $41,917,701.00 | 3.514× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $6.36 | $3.18 | $9.53 |
| 75 | dcsRXkSdoZ2bE95YXJW5zdbaPAx2AMFiBQgKbYupump | 2026-08-04 10:30:00.037537 | $46,183,242.00 | 3.426× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $9.53 | $4.77 | $14.30 |
| 76 | ttVMuedwGUM48GsPpVjLjNF4mvh7832WCFpCMkypump | 2026-08-04 11:30:00.097334 | $266,599.00 | 1.402× | 0.005× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $14.30 | $-3.58 | $10.73 |
| 77 | 5VbMioVZem8cyWnst51DKJSo2xko6daYxqdcNkDQpump | 2026-08-04 11:45:00.033536 | $26,573,141.00 | 1.789× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $10.73 | $5.36 | $16.09 |
| 78 | DmFhhWM2MHBVdnifRsKznExXaAGkaGaqsnywVua8pump | 2026-08-04 13:00:00.035833 | $7,291.00 | 1.201× | 0.234× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $16.09 | $-4.02 | $12.07 |
| 79 | 12LzvfmSCWHRFjLfidX3EczZJGQNbzyWWZaVnXScpump | 2026-08-04 13:29:48.563729 | $22,225.00 | 1.291× | 0.149× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $12.07 | $-3.02 | $9.05 |
| 80 | 8sTDvPY27UJwdavPMYrKG9eSHaotp6rngQh9nipFpump | 2026-08-04 13:30:00.005761 | $1,861.00 | 1.021× | 0.965× | N | N | OPEN | OPEN | -3.55% mark | $9.05 | UNSETTLED | UNSETTLED |
| 81 | CmzacHm3ob14huUYYhzaPcPcCgTVLDCBU6nSjxzvpump | 2026-08-04 13:30:00.005761 | $238,460.00 | 0.854× | 0.018× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $9.05 | $-2.26 | $6.79 |
| 82 | 8WGgZ64E9Nf9wAj3VrBLc2Z5epENB2KFu6UH6hP2pump | 2026-08-04 14:10:58.538360 | $1,381.00 | 1.014× | 1.000× | N | N | OPEN | OPEN | 1.45% mark | $6.79 | UNSETTLED | UNSETTLED |
| 83 | 9E54wVJ2kfAFjByXFVn6V7Gna9cYriKASmCvH1xzpump | 2026-08-04 14:10:58.538360 | $1,456.00 | 1.000× | 0.919× | N | N | OPEN | OPEN | -6.87% mark | $6.79 | UNSETTLED | UNSETTLED |
| 84 | BWG9ChhncUx9KkRoycT2uuQL7pV4PjykDPgXqWuwpump | 2026-08-04 14:30:00.036893 | $42,214,441.00 | 1.185× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $6.79 | $-1.70 | $5.09 |
| 85 | DgCpBrRoKjf9tS9dk7mNVRDEoSxRRFjPHJNUiYsXpump | 2026-08-04 15:00:00.030548 | $204,802.00 | 1.383× | 0.007× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $5.09 | $-1.27 | $3.82 |
| 86 | Tt9EtDDyen6ow6aqxSHyYcj9oRb7zuZkvkDigbDpump | 2026-08-04 15:45:00.095012 | $192,302.00 | 1.010× | 0.013× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $3.82 | $-0.95 | $2.86 |
| 87 | 5YzGccQfADG94CY28rboF64GQvFeGTM5U5Rvt22Kpump | 2026-08-04 18:30:00.013172 | $138,455.00 | 0.882× | 0.010× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.86 | $-0.72 | $2.15 |
| 88 | Ef4E8vBoosFWhxXWqRHQAsXiuuAbocrN9PnpgHNrpump | 2026-08-04 18:30:00.013172 | $144,999.00 | 3.223× | 0.047× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.15 | $-0.54 | $1.61 |
| 89 | D8yEyFTE1bFBP3MJeDocajNFasgBdpt6fSHxqotrpump | 2026-08-04 18:45:00.126084 | $95,385.00 | 1.448× | 0.018× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.61 | $-0.40 | $1.21 |
| 90 | 2sQ7wuUtRWNir3CEu9HWfLDSut4AszDrcZXLobzJpump | 2026-08-04 19:00:00.011491 | $523,540.00 | 2.303× | 0.472× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.21 | $0.60 | $1.81 |
| 91 | 7C17GMDWxy2wCggRXEKKeTY21B84mT9vv9c6b1vTpump | 2026-08-04 19:00:00.011491 | $43,863.00 | 4.585× | 0.094× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.81 | $-0.45 | $1.36 |
| 92 | omCw7YKqosQkTaeKoLKFBeXyLUxtqg7Prr1kUoZpump | 2026-08-04 19:00:00.011491 | $32,402,209.00 | 1.786× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.36 | $0.68 | $2.04 |
| 93 | 7Fmyfurek9n29Abvmm7KMqa8mfNApY8qtrqURqiYpump | 2026-08-04 19:30:00.293576 | $69,427,842.00 | 1.096× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.04 | $-0.51 | $1.53 |
| 94 | EhhhiNyiomwdTjHiGrLTtxvHcNg4Vh9gNX4TUFvWpump | 2026-08-04 19:30:00.293576 | $43,789.00 | 1.000× | 0.053× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.53 | $-0.38 | $1.15 |
| 95 | pcbXE59bWKc5VmueJbs58vYCRfjCHqnP59iocAwpump | 2026-08-04 19:30:00.293576 | $4,988,189.00 | 1.076× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.15 | $-0.29 | $0.86 |
| 96 | yQii1bE6iRpDSeGRSkF2z3vYYBHiWN9CWJ4ckr9pump | 2026-08-04 19:30:00.293576 | $1,608,228.00 | 1.751× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.86 | $0.43 | $1.29 |
| 97 | 25g5Ay42aip4BZN8KWWA79jiY2VYykuMg4qdBDsapump | 2026-08-04 19:45:00.043447 | $192,762.00 | 1.465× | 0.013× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.29 | $-0.32 | $0.97 |
| 98 | jmM56TE7ko4jUzmzJ523W1b3872jMXKoiwsJLUKpump | 2026-08-04 19:45:00.043447 | $13,160,369.00 | 1.029× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.97 | $-0.24 | $0.73 |
| 99 | 2QX56DqmSmXiwfHTTuHAL24U65jzjnQvYiogqY9Npump | 2026-08-04 20:00:00.071076 | $29,581.00 | 1.003× | 0.606× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.73 | $-0.18 | $0.54 |
| 100 | DEA7Kjg3gdmim2z79o5c6UW7qXZirtJGociuJDAKpump | 2026-08-04 20:30:00.136315 | $193,999.00 | 1.199× | 0.008× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.54 | $-0.14 | $0.41 |
| 101 | 7jFpDComUfCZnFrG65CR9wyDesFtA5oJPvUMdfuopump | 2026-08-04 20:45:00.111064 | $89,133.00 | 3.091× | 0.042× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.41 | $0.20 | $0.61 |
| 102 | 2xXfAYYxLZEqmYVDZt4DbGd8KaYpLqULDwWbRwrJpump | 2026-08-04 22:34:22.661423 | $71,586.00 | 2.997× | 0.037× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.61 | $0.31 | $0.92 |
| 103 | 8T3suJtKUGrWRytVNKe7RLV81AumvmBPQfEkyeHtpump | 2026-08-04 23:26:54.824102 | $16,126.00 | 2.770× | 0.819× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.92 | $0.46 | $1.38 |
| 104 | 3e53B7z3kkWcp9NrpJsRC5e5U6sNwxbHXmAXBH5tpump | 2026-08-05 00:26:33.207077 | $112,002.00 | 3.921× | 0.016× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.38 | $0.69 | $2.07 |
| 105 | fQyy5gfoKdBqajJmfzFm9eVTvkAPrpkfU1xuUdupump | 2026-08-05 02:58:53.573470 | $5,956,415.00 | 1.161× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.07 | $-0.52 | $1.55 |
| 106 | 9fa8sGn7VBJFcFnARkM964HmE2sBWd9aChguknLQpump | 2026-08-05 03:36:14.458964 | $1,723.00 | 1.000× | 0.986× | N | N | OPEN | OPEN | -1.39% mark | $1.55 | UNSETTLED | UNSETTLED |
| 107 | 9tHcEczMZCD7KvLgSibhxvhPt9wFxdmkgzWrSuQrpump | 2026-08-05 03:36:14.458964 | $1,731.00 | 1.251× | 0.908× | N | N | OPEN | OPEN | -6.12% mark | $1.55 | UNSETTLED | UNSETTLED |
| 108 | kpmhzGSYni1ta6Crc1xRDne2g7NTuEmmNJpDxwvpump | 2026-08-05 03:36:14.458964 | $3,702,334.00 | 1.723× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.55 | $0.77 | $2.32 |
| 109 | Szba5dpJC7h9KqVy84WFvgwhxsuP1LKpPFcvSMUpump | 2026-08-05 04:35:29.683250 | $103,752.00 | 0.808× | 0.016× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.32 | $-0.58 | $1.74 |
| 110 | BBhTbMvpQMgsoMdhHC4RQaw66aDGFr4QuHZxKdmxpump | 2026-08-05 06:00:00.025112 | $4,678.00 | 16.454× | 0.807× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.74 | $0.87 | $2.62 |
| 111 | 535ES1hrVy9SwLUkouawQeoXSkPB2zGXhTU222enbZWU | 2026-08-05 06:15:00.045867 | $122,509.00 | 1.509× | 0.011× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $2.62 | $1.31 | $3.92 |
| 112 | Gk1vw7FFUsijxz1DaFhn9RL99dNQo6NVkjjfxojpump | 2026-08-05 06:15:00.045867 | $751,256.00 | 1.282× | 0.002× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $3.92 | $-0.98 | $2.94 |
| 113 | 7AmvhUHDXXRAiWo2SU5YVcV9MqshxUpABi5jD8SCqJ69 | 2026-08-05 06:30:00.053760 | $21,977.00 | 3.810× | 0.077× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.94 | $-0.74 | $2.21 |
| 114 | 9XJ2YD29HKnCsGKHFuVvPsrNBshFi77FjxB3ay7BbBuq | 2026-08-05 06:30:00.053760 | $1,136,174.00 | 1.558× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $2.21 | $1.10 | $3.31 |
| 115 | DnmdeUqUxyGKRd5WN4nfSZP3zbzG3giB6vaERD4apump | 2026-08-05 06:30:00.053760 | $81,200.00 | 1.834× | 0.025× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $3.31 | $1.65 | $4.96 |
| 116 | E4qqbDBohC7RCeojD6rYY7MzctiK62gFZVEqv4fwpump | 2026-08-05 06:45:00.030966 | $36,604.00 | 2.020× | 0.037× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $4.96 | $2.48 | $7.45 |
| 117 | m7dCz1i6eYa29ruvn4JJR7Ye5H5EVK7NbP99LFFpump | 2026-08-05 06:45:00.030966 | $7,849,727.00 | 1.400× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $7.45 | $-1.86 | $5.59 |
| 118 | Hroe4anfjdcPxUExCb4XqKWdc3Ddxh7bHEJfMaN4pump | 2026-08-05 07:00:00.451213 | $34,828.00 | 0.044× | 0.039× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $5.59 | $-1.40 | $4.19 |
| 119 | 8wQR89A1iWYuQWQqrDsCTfszmPj36HzPt51jQyZmpump | 2026-08-05 07:15:00.037933 | $91,506.00 | 1.093× | 0.018× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $4.19 | $-1.05 | $3.14 |
| 120 | b1RRNfiWohWqGPDTgLcxUnVhaHis13RsEQFuNkYpump | 2026-08-05 07:30:00.033111 | $39,730,502.00 | 1.031× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $3.14 | $-0.79 | $2.36 |
| 121 | 7WmG1z9ysDhAWY7vCGkbhAG3zCaVUzzZrEAUj1hjpump | 2026-08-05 07:45:00.028478 | $42,163.00 | 6.835× | 0.104× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $2.36 | $1.18 | $3.53 |
| 122 | 9j4SqT7hR6BAkHaZFvLUBH3hYZdU66ZN7JgECKaCpump | 2026-08-05 07:45:00.028478 | $445,202.00 | 1.033× | 0.003× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $3.53 | $-0.88 | $2.65 |
| 123 | 9nNsfWWY6mrEnREHkW1Q1LZMyWwvvXzg6uXR3ZKmpump | 2026-08-05 07:45:00.028478 | $102,335.00 | 1.262× | 0.021× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.65 | $-0.66 | $1.99 |
| 124 | mFygiaBQTAH2GH2z4PDwjZcyAM79LNc99wD2KHmpump | 2026-08-05 08:02:28.834383 | $4,600,283.00 | 1.770× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.99 | $0.99 | $2.98 |
| 125 | 5QucdUZXFzNcJ1NoP7Rj1JYDpSKbRsKUaTa6VjMupump | 2026-08-05 08:41:42.043429 | $2,013.00 | 1.025× | 0.796× | N | N | OPEN | OPEN | -17.34% mark | $2.98 | UNSETTLED | UNSETTLED |
| 126 | BJe2XQMc22wQvwbXr1ai8QfymiP6AwQzcRBu3PEfpump | 2026-08-05 08:41:42.043429 | $21,630,762.00 | 1.474× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.98 | $-0.75 | $2.24 |
| 127 | Gv42Kd1vxEfw8gaHukByqafxWMCJhqSukTumFN15pump | 2026-08-05 10:15:00.179463 | $131,611.00 | 1.262× | 0.012× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.24 | $-0.56 | $1.68 |
| 128 | BSLdyn9RGoBNg9G28AfZFfDU6WRbCrZQvktWdRLhpump | 2026-08-05 10:30:00.149453 | $11,266.00 | 1.000× | 0.129× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.68 | $-0.42 | $1.26 |
| 129 | Aq2idw7BeJX2WfNek6jGnp1z2s79CpFYZXo2zCF1pump | 2026-08-05 12:00:00.026823 | $111,198.00 | 1.910× | 0.058× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.26 | $0.63 | $1.89 |
| 130 | HG6dbpS5NS6eaL1eGQhySa3NGX83s58eowg5ucCcpump | 2026-08-05 12:15:39.397734 | $18,938.00 | 1.220× | 0.939× | N | N | OPEN | OPEN | 21.65% mark | $1.89 | UNSETTLED | UNSETTLED |
| 131 | FcaEwSgoFtu2EAry7cKAfncBY42xgiuaSJYHwRcvpump | 2026-08-05 13:15:00.064219 | $122,497.00 | 1.321× | 0.013× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.89 | $-0.47 | $1.42 |
| 132 | 9CcoWrWhbfhK54opzHEuv3u281b3eKyDcafAtS6apump | 2026-08-05 13:30:00.012740 | $39,970.00 | 2.743× | 0.084× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.42 | $-0.35 | $1.06 |
| 133 | EBZh975canPjxZzY4rTmb4JrBWaU7MmeKmXZFyQ2pump | 2026-08-05 13:30:00.012740 | $70,378.00 | 2.005× | 0.021× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.06 | $0.53 | $1.59 |
| 134 | Pi4QesT6bd9HHMSTkBuz7wHXYxHEQCZMkZrAbU6pump | 2026-08-05 13:30:00.012740 | $41,009,369.00 | 2.607× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $1.59 | $0.80 | $2.39 |
| 135 | 8Xzg97u3kq6ikwyAznRyNiviQu3Hvqq9Xtp6X85Dpump | 2026-08-05 15:42:46.355149 | $11,809.00 | 0.600× | 0.124× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $2.39 | $-0.60 | $1.79 |
| 136 | EwwGk4WmevQ7mzX5caz7UCcj9HTGCcW519NCKMWTpump | 2026-08-05 16:15:00.226202 | $56,854,335.00 | 1.088× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.79 | $-0.45 | $1.34 |
| 137 | 71BGRxYJdi2ZvFuzTSNuK5A8YSpeXHRgXpE4GGmapump | 2026-08-05 18:59:58.091378 | $2,907.00 | 1.334× | 0.982× | N | N | OPEN | OPEN | 28.62% mark | $1.34 | UNSETTLED | UNSETTLED |
| 138 | 8kFboZiKNQ4jC8fyNAiCjm9YGV5qs99Ns7fCchdYpump | 2026-08-05 19:54:21.970455 | $1,717.00 | 1.161× | 0.996× | N | N | OPEN | OPEN | 4.31% mark | $1.34 | UNSETTLED | UNSETTLED |
| 139 | 5SUcWZYjXh9HTLoqP8pGFck34Y7QHrZZijwXY6cNpump | 2026-08-05 20:55:59.682711 | $4,304.00 | 1.119× | 0.479× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.34 | $-0.34 | $1.01 |
| 140 | 59iKfdEM66xZmNVUmogYiSEncwKTMrCeAXyjCdHbpump | 2026-08-05 23:59:24.290918 | $2,135.00 | 1.099× | 0.701× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $1.01 | $-0.25 | $0.76 |
| 141 | 7FsLn4KTZUaSK111eaTyVZbe2Y6RuoKamMfVDF71pump | 2026-08-06 06:54:03.428263 | $3,153.00 | 1.272× | 0.602× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.76 | $-0.19 | $0.57 |
| 142 | G7biqxzVp1xsxevqCCkCiYnweikDMKmK3q8LPHKNc1ip | 2026-08-06 08:17:46.324550 | $358,704.00 | 0.811× | 0.010× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.57 | $-0.14 | $0.43 |
| 143 | 41wFZXSSjyiaQE97pRMqodTSwYxnV4ryX6XYfEs3pump | 2026-08-06 11:30:00.024857 | $8,993.00 | 2.477× | 0.917× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.43 | $0.21 | $0.64 |
| 144 | 81thxVdQByiDe8fY16ThwJ2xVj2QSRhkMo8u76SHpump | 2026-08-06 13:04:04.296199 | $2,322.00 | 0.930× | 0.766× | N | N | OPEN | OPEN | -22.65% mark | $0.64 | UNSETTLED | UNSETTLED |
| 145 | B88dwNrMyZ3ZZvq8ZXHnbisWzG5WQ5EaJ3dud1REpump | 2026-08-06 16:00:36.380245 | $2,580.00 | 1.171× | 0.805× | N | N | OPEN | OPEN | -4.53% mark | $0.64 | UNSETTLED | UNSETTLED |
| 146 | CjRtyRTbwBgtbpDshAa6uAHP8UPMDqioFZATdBqmpump | 2026-08-06 16:15:00.272781 | $19,569.00 | 1.741× | 0.107× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.64 | $-0.16 | $0.48 |
| 147 | ANWSnRAdxuzsReerVCHSVLzYoFn8P4husnfufBBxpump | 2026-08-06 16:30:00.034735 | $4,711.00 | 1.249× | 0.317× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.48 | $-0.12 | $0.36 |
| 148 | 6RDmo8ox2d4jpqZkxjD99S185rUmK5xC9pkGtdzQpump | 2026-08-06 16:45:00.250792 | $6,595.00 | 1.791× | 0.257× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.36 | $-0.09 | $0.27 |
| 149 | 2whPG8LS8ZdttCRdr1EoWxJNmdm76NjpguKKbJfCpump | 2026-08-06 17:00:00.015844 | $628,755.00 | 1.246× | 0.002× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.27 | $-0.07 | $0.20 |
| 150 | EJFseq4RFonjh9u6bzYLFynJin9WLKHF7jCgVoSXpump | 2026-08-06 17:00:00.015844 | $63,670.00 | 1.016× | 0.041× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.20 | $-0.05 | $0.15 |
| 151 | 2tBjFsno9tdkX7AhZ9uehAet5o8GninkrqDYZZYUpump | 2026-08-06 17:15:00.195824 | $62,341.00 | 5.498× | 0.044× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.15 | $0.08 | $0.23 |
| 152 | CpVpZfyPXjgPnshbjishBtMuyoX6VRBzptjmtfPnjecz | 2026-08-06 17:15:00.195824 | $4,447,692.00 | 1.712× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.23 | $0.11 | $0.34 |
| 153 | FLXKUaytEgJQFMzwnAwiSBs2SJ8a2BjvcaYQEkNRpump | 2026-08-06 17:15:00.195824 | $286,666.00 | 1.419× | 0.006× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.34 | $-0.09 | $0.26 |
| 154 | Fo1jurQMNo2GxGBFPpBcYpLSv8iVa5xNDHazCATXpump | 2026-08-06 17:15:00.195824 | $5,487,152.00 | 2.752× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.26 | $0.13 | $0.38 |
| 155 | GCTzj4VjKwK2K8edGfJgQ8oMhPVPBrrsuUZHpePpump | 2026-08-06 17:15:00.195824 | $1,021,696.00 | 1.181× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.38 | $-0.10 | $0.29 |
| 156 | 63uVjAW8mCm72hwz75UGV13xHmdjPQfcAAfKWDwBpump | 2026-08-06 17:30:00.184926 | $37,547.00 | 0.924× | 0.039× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.29 | $-0.07 | $0.22 |
| 157 | EhKTqNSB2ZCFbWesj9faf38JUGSJxtaVAdHCv2bUpump | 2026-08-06 17:30:00.184926 | $178,029.00 | 1.618× | 0.008× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.22 | $0.11 | $0.32 |
| 158 | oxsBtVM2ph6TWDZjKeLxuq77kQLBNBmdTcZDXcGpump | 2026-08-06 17:30:00.184926 | $5,532,355.00 | 1.351× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.32 | $-0.08 | $0.24 |
| 159 | yHFCN8hgkuczUHas3nGHwcBEJGcQH8f1KaJJiGopump | 2026-08-06 17:30:00.184926 | $1,961.00 | 1.121× | 0.957× | N | N | OPEN | OPEN | -2.29% mark | $0.24 | UNSETTLED | UNSETTLED |
| 160 | C8v831nRhkdHRk2CK429EroVq5JSQUXytWMLWjdPpump | 2026-08-06 18:00:00.022059 | $10,910,581.00 | 1.710× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.24 | $0.12 | $0.36 |
| 161 | CASVQ4LuLS9BRfDf8ixVTonfwyQ4oEdm7hVsb1Pxpump | 2026-08-06 18:00:00.022059 | $1,201,215.00 | 1.236× | 0.043× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.36 | $-0.09 | $0.27 |
| 162 | D88sdARwWoiv6XZUBvMmeiGiLYhvurwe5EreuLTnpump | 2026-08-06 18:00:00.022059 | $69,884.00 | 1.243× | 0.036× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.27 | $-0.07 | $0.20 |
| 163 | DHKfiAzT1uhMXdLZyHzbPU1TmVX7jgR4rkeYcQq3pump | 2026-08-06 18:00:00.022059 | $29,825.00 | 2.812× | 0.066× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.20 | $0.10 | $0.31 |
| 164 | Fcbmm7MMoyGB31c4MEsdqNDLvDh92xRCsnQtDsVZpump | 2026-08-06 18:00:00.022059 | $964,572.00 | 1.610× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.31 | $0.15 | $0.46 |
| 165 | Hb5gAssobeM4yxjtxS8RtVUyLn3dYY5QtpipPtjspump | 2026-08-06 18:00:00.022059 | $44,782,477.00 | 1.174× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.46 | $-0.12 | $0.35 |
| 166 | Dmw8cdpz5RVDvBgNYmJd2AXgjyjitw8gd99CLWLXpump | 2026-08-06 18:15:00.007218 | $6,901,240.00 | 1.061× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.35 | $-0.09 | $0.26 |
| 167 | 2KBM65dRrGYBiHqxxz6yLQzyMxCkmMYnGc2z1Thepump | 2026-08-06 18:30:00.023191 | $5,029.00 | 1.000× | 0.337× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.26 | $-0.06 | $0.19 |
| 168 | 9dwHn2KWApoGj4MeMLVGFuqDLLWqhDRkpEGCjGmcpump | 2026-08-06 18:30:00.023191 | $122,918,626.00 | 6.557× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.19 | $0.10 | $0.29 |
| 169 | GkGgm2zkFSS5zioBRMPvD7LR2MWyrDiewYjm2A6cpump | 2026-08-06 18:30:00.023191 | $31,281.00 | 0.167× | 0.060× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.29 | $-0.07 | $0.22 |
| 170 | tDiotxQZd8nq7gpNkrigcuX4xMwahdfYu96JYX2pump | 2026-08-06 19:09:51.817397 | $1,780.00 | 1.000× | 0.787× | N | N | OPEN | OPEN | -19.89% mark | $0.22 | UNSETTLED | UNSETTLED |
| 171 | 2A8k5ocszu6QGUQeHjixWEF42Wt9H8AbxQRtJhKzpump | 2026-08-06 20:33:42.059436 | $12,183.00 | 1.000× | 0.141× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.22 | $-0.05 | $0.16 |
| 172 | DRD2PskD1XdmtcYw8QTUwnnwx5FwDvRbrSY69bb8pump | 2026-08-06 22:10:47.479366 | $2,514.00 | 1.042× | 0.642× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.16 | $-0.04 | $0.12 |
| 173 | DxnPojFH2FfeEqwq6DhBhEFEyvrgbeTNZ3tSUW3rpump | 2026-08-06 22:10:47.479366 | $4,182,979.00 | 1.746× | 0.043× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.12 | $0.06 | $0.18 |
| 174 | 54EwFzxvcPPDr171tMxP2Bm6xkWTdBgBkuvNs8Lypump | 2026-08-07 00:11:35.574523 | $57,491.00 | 1.136× | 0.036× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.18 | $-0.05 | $0.14 |
| 175 | 67DRARNLy41ThohBNtRNHKugBr5Md8BbWdbbMjD4pump | 2026-08-07 01:30:50.015171 | $6,416,445.00 | 1.071× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.14 | $-0.03 | $0.10 |
| 176 | 21BTR4m7ndap1mqq6MobR7S4SQZrum8YfznEuoExpump | 2026-08-07 03:32:48.092229 | $2,144.00 | 1.131× | 0.667× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.10 | $-0.03 | $0.08 |
| 177 | 8PHMWdhEebimpHhKttncRFFojWiCpBUF4dWScybXpump | 2026-08-07 04:37:09.037635 | $1,902.00 | 1.186× | 0.808× | N | N | OPEN | OPEN | -19.19% mark | $0.08 | UNSETTLED | UNSETTLED |
| 178 | AFKSaegQGG2H2MThj8VK87LUkir6vbgLEma6NTFzpump | 2026-08-07 06:45:32.797722 | $25,235.00 | 1.174× | 0.312× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.08 | $-0.02 | $0.06 |
| 179 | 4RjmvMSmUcRofRLkudu8C4XAwxxmx2tErAdHqQfwpump | 2026-08-07 07:16:32.713578 | $5,742.00 | 1.000× | 0.249× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.06 | $-0.01 | $0.04 |
| 180 | H6QbkNxaVKuwhRLRFpRBhBubqGuPk5bqs2NyVf4epump | 2026-08-07 07:16:32.713578 | $1,730.00 | 1.084× | 0.999× | N | N | OPEN | OPEN | 5.84% mark | $0.04 | UNSETTLED | UNSETTLED |
| 181 | 66ToQGqXFDGN4xqi7b1uoiidWnah36X53Dc3PyRdpump | 2026-08-07 08:00:02.225210 | $64,982.00 | 1.510× | 0.024× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.04 | $-0.01 | $0.03 |
| 182 | AYM32hqEXzYjfoGWR743pV8jE6c68SqKMMhKTdxzpump | 2026-08-07 08:00:02.225210 | $154,445.00 | 1.510× | 0.011× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.03 | $-0.01 | $0.02 |
| 183 | B58hjChWDokgr3TjEFVSpwb6f7XWhEMTqx2WXYmrpump | 2026-08-07 08:00:02.225210 | $62,410.00 | 0.937× | 0.030× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.02 | $-0.01 | $0.02 |
| 184 | CdKQLGogBTECMzYaDkU4uounyNKVxU8L5S8titQKpump | 2026-08-07 08:00:02.225210 | $71,539.00 | 2.469× | 0.023× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.02 | $0.01 | $0.03 |
| 185 | 89LQmLpgxM53SMaNCeX1KuNjUQCTqdqvyt1rzmR1pump | 2026-08-07 08:15:00.088312 | $137,155.00 | 1.126× | 0.016× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.03 | $-0.01 | $0.02 |
| 186 | DfuGsM6Zp3AMXL76w8N8m8iHjo8nRCgeCS138AKCpump | 2026-08-07 08:15:00.088312 | $142,078.00 | 1.461× | 0.012× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.02 | $-0.01 | $0.02 |
| 187 | Dwm6hJL8ax8jttdj1TFFnLSuPo474FEdV3c14Vnnh2Yi | 2026-08-07 08:15:00.088312 | $28,922.00 | 1.317× | 0.054× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.02 | $-0.00 | $0.01 |
| 188 | F2uXeJ2ZiZFrwdpDvGDGuNFKcZHbfuuZzVDwgSMJpump | 2026-08-07 09:01:59.317859 | $34,036.00 | 2.543× | 0.042× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.01 | $0.01 | $0.02 |
| 189 | 8gL6cRbgB1xa5wmm3k6rv61DU7wGgYFqDgX7zaVnpump | 2026-08-07 11:19:15.261211 | $16,713.00 | 1.075× | 0.088× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.02 | $-0.00 | $0.01 |
| 190 | HFAEmjnBoRAETYiEq4fpF8hQFV69q3W826zaU7Tb4tFS | 2026-08-07 12:30:00.468848 | $2,087.00 | 1.001× | 0.683× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.01 |
| 191 | 4zcHY8W9iePgJG5wkQvw5JDxTjNAYTqmYukWrz1spump | 2026-08-07 13:45:00.029289 | $33,183.00 | 1.420× | 0.056× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.01 |
| 192 | J9QNvnbY5cHDAFzH8VJHCFi6y2q7KWkYJ88tiegpump | 2026-08-07 13:45:00.029289 | $2,793.00 | 1.000× | 0.759× | N | N | OPEN | OPEN | -24.13% mark | $0.01 | UNSETTLED | UNSETTLED |
| 193 | 745a6Rb51P2MDig8nxWfctxsz7PQvodeqa1WTSRwpump | 2026-08-07 14:12:55.335102 | $16,361.00 | 0.960× | 0.126× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.01 |
| 194 | 4v6Y3tS3oT6bqcybHX9jWk8mS5PAU4ZFL8ZuiAcBpump | 2026-08-07 14:57:08.181048 | $3,424.00 | 2.475× | 0.684× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.00 |
| 195 | 7U3io2T7S9ce2hpyLCejHBDQV5Q4UEDAPeshxSm2pump | 2026-08-07 15:45:00.062636 | $137,547.00 | 4.496× | 0.037× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.01 |
| 196 | 9umk2MS7CmCChhVZxaiuEY8nCJcYcYTcBkFssFzEpump | 2026-08-07 16:00:00.105059 | $21,375.00 | 1.346× | 0.071× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.00 |
| 197 | 9Z8v2qFg4igA6XCMLXqvU9LKQy95Grw7g344cs6npump | 2026-08-07 16:15:00.616727 | $3,036.00 | 1.000× | 0.508× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 198 | BRdJ82GSiJKTzjjRh4ABK9VGoy7BjzzjVLYGLdedpump | 2026-08-07 16:30:00.108896 | $22,079.00 | 1.586× | 0.070× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 199 | wyVF24D5d7WwaRFtDboPcLmRp6PpjFsY9YGhVqXpump | 2026-08-07 16:30:00.108896 | $6,891,471.00 | 1.544× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 200 | mNzssXQ9hU1ASJ1CVuu4JjrFBrfeVdR2JzirKS3pump | 2026-08-07 16:45:00.314854 | $689,056.00 | 8.996× | 0.004× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.01 |
| 201 | Bfn8na1BJEdigTVpe9BjBGv7DFAKRgJUAVYVFk5Vpump | 2026-08-07 18:15:00.905239 | $1,931.00 | 1.272× | 0.976× | N | N | OPEN | OPEN | -2.38% mark | $0.01 | UNSETTLED | UNSETTLED |
| 202 | Edpcd9aYh6BVRKV5hYrgnEuJ3MHAFcdnHtSL9yvopump | 2026-08-07 18:15:00.905239 | $85,346.00 | 1.787× | 0.828× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.01 | $0.00 | $0.01 |
| 203 | 4eYp69P1VU946efStVzV41gQvYjMucpcuYEbofc6pump | 2026-08-07 19:00:00.200883 | $27,914.00 | 1.170× | 0.065× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.01 |
| 204 | EWkxWDjmVU9ren399TLaiYoss1bBwFeKDBAHb1Dapump | 2026-08-07 19:00:00.200883 | $43,683.00 | 3.488× | 0.032× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.00 |
| 205 | D1JJKw2BWCxSNPECFcTZG9mEPZUUDDLoTMWw3LDbpump | 2026-08-07 19:15:00.091566 | $34,012.00 | 1.063× | 0.045× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 206 | 9pv39fsTSPcDwj4GCnDMoBG7qjSs1YzbhwGonvs8pump | 2026-08-07 19:51:04.267319 | $34,347.00 | 1.000× | 0.069× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 207 | DgwLa53Xr8VbGGadB5MP9X469kBk36k6XfEccNnSpump | 2026-08-07 19:51:04.267319 | $23,879.00 | 1.090× | 0.070× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 208 | BJWHLmtbabbby7LstVRvo4Q39oER9C1TrzR3gpTHpump | 2026-08-07 21:17:27.532867 | $185,637.00 | 0.955× | 0.050× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 209 | DywWmg5WEAPYo2YoKcWgXpdLdzCn1Hwva1pnQBwUpump | 2026-08-08 05:15:37.871739 | $4,489.00 | 1.357× | 0.331× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 210 | br8Ra5Gmz5yXecFh3MGUBEvT9Pp7rJEKGNBLq7Cpump | 2026-08-08 06:15:01.296703 | $2,250,464.00 | 1.642× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 211 | BP1pNDqzvVmedqVZtB8qvGsohisj2wcFmb98fjrpump | 2026-08-08 06:30:00.029815 | $677,085.00 | 1.460× | 0.002× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 212 | MAUKik8JvQ6Zbcpv4naMyfYFbWd9v18N9uLvzVCpump | 2026-08-08 06:45:00.043794 | $101,442.00 | 1.815× | 0.014× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 213 | 2qE4vpAj5zv3WDCUdsxkdDwLboqC3PZk9caa3DjApump | 2026-08-08 07:45:00.028444 | $58,134.00 | 2.365× | 0.026× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 214 | 3RoinFB8cgCTcYvSJd1bsGjd27YaNBL1tz9eCbSupump | 2026-08-08 07:45:00.028444 | $19,405.00 | 1.009× | 0.090× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 215 | gZfjo3669AanbQz3GMXbxhDUUg8ibHxVPdQtWH2pump | 2026-08-08 07:45:00.028444 | $576,918.00 | 1.276× | 0.002× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 216 | FhY3sugZdts453pcU1W9ZJ78FfudVHHnKcDupny2pump | 2026-08-08 08:00:00.016085 | $60,219.00 | 1.995× | 0.025× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 217 | Xyj8Lb4t2UmuJU2bLijkbZNHxTdSTCyyteWhAGzpump | 2026-08-08 08:00:00.016085 | $4,520,690.00 | 1.930× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 218 | 46amR3aeQE7MJ9QDrgNRqBP3FcsJ9QNYV71L2vVSpump | 2026-08-08 08:15:00.695612 | $36,363.00 | 39.177× | 0.481× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 219 | EceWZ2UAExDHSCxBJhwc4PeGzQ18zhytDS8YaWFLpump | 2026-08-08 08:15:00.695612 | $28,025.00 | 1.494× | 0.052× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 220 | 83eCQAsnRzUnpa9LF1ErU2m7TiRGrCJX22JDK2MNpump | 2026-08-08 08:45:01.468782 | $45,159.00 | 1.369× | 0.036× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 221 | 3APmL2adpfnmd1MeCcMySXQqHLViNubMS3CmwBY1pump | 2026-08-08 09:00:00.082776 | $58,577.00 | 3.280× | 0.029× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 222 | 7B84vZKDNya59tiR6Rbonzc8Fj1JqtVB7uw3JnNZpump | 2026-08-08 09:00:00.082776 | $30,441.00 | 1.852× | 0.066× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 223 | B2Wm5njbGdc1JdahcPB3tEww6BCoQCUQM4suojCppump | 2026-08-08 09:00:00.082776 | $69,936,746.00 | 1.246× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 224 | B7Yt9TBjNSv3UwGfPQmJfgc5exSzf5Rq2ePVNux3pump | 2026-08-08 09:30:00.126494 | $67,443.00 | 3.310× | 0.065× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 225 | BLd2N76AEHM6P7QrQMX6nvFwVXw9X85mHgLuXXztpump | 2026-08-08 09:30:00.126494 | $12,801,560.00 | 1.033× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 226 | F1XdReoHL3GweeCG4sgoZGAdsUNt8sda8n5EE2TNpump | 2026-08-08 09:45:00.097025 | $58,281.00 | 9.032× | 0.208× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 227 | iuKqr794GeP4pJE4EGsVTJWwBJm6MWTuwCJyQXQpump | 2026-08-08 09:45:00.097025 | $2,628,684.00 | 1.085× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 228 | D5jArFXKp49srvwKUnVQJXaTyES2RuxL1ZZVZmYGpump | 2026-08-08 10:00:00.029650 | $25,101.00 | 1.055× | 0.075× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 229 | Etn5sZVyKfYY3tqLqctEA4sqKW5Psy221wKNo7K6pump | 2026-08-08 10:30:00.048617 | $37,368.00 | 2.698× | 0.064× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 230 | H3YNxt32PnJsoHGUL4ei743zyNo8At9nVXf5jg3Epump | 2026-08-08 10:30:00.048617 | $1,925,170.00 | 1.347× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 231 | FFR3KzjZh6F2TSocKCd2bYaT9TKfTuVeu9T1WLkUPJ5q | 2026-08-08 10:45:00.158223 | $5,641.00 | 1.777× | 0.279× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 232 | QhnVFwLx9m9h2yA1CZkqTcnNkTCXx2gZNuzJn4ipump | 2026-08-08 10:45:00.158223 | $96,377,387.00 | 1.930× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 233 | FnezYruxKeGBPEA9FxK1eNYZcRmfz7ZYQRExa5fypump | 2026-08-08 11:15:01.242984 | $109,445.00 | 1.101× | 0.017× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 234 | 78Dkc1XxEa5VDqyNs3657gkuoGnp2ApgqHjx11Zf4vhr | 2026-08-08 12:15:00.222174 | $34,546.00 | 4.299× | 0.428× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 235 | G9Xh5ZFZr3dD2aCZuSYfGX1gwB1iy1jwBNQjhB79pump | 2026-08-08 12:15:00.222174 | $3,584.00 | 1.004× | 0.412× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 236 | eQED4ERMLjDqajpFuiFt14XhhtjbMzfdhtpaGbqpump | 2026-08-08 12:15:00.222174 | $106,377,420.00 | 1.678× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 237 | 9fWLWwvHPuLjQiL65tU4bXf6jsB4L9TQXVWuWveXpump | 2026-08-08 12:45:00.547034 | $3,656.00 | 1.000× | 0.479× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 238 | EjD5Y9NVhXmtEqU7wYvAyZvDWZFQeEuHXFatJmTbpump | 2026-08-08 13:15:04.755767 | $50,216.00 | 33.888× | 0.017× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 239 | 7hmVkPXmVagxoptAEpx4jBzZVHwGLdFj6c1y42qxpump | 2026-08-08 13:30:00.218231 | $1,338,059.00 | 1.015× | 0.334× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 240 | TzvZvrzebyxdCLvesr2Xx4xepoyY3ngvNNgkumDpump | 2026-08-08 13:45:01.272143 | $111,881,328.00 | 2.784× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.01 |
| 241 | G3M3rDfcGp3BQ3pnxeykzGyTUTLHzZ34QeyFmvCFpump | 2026-08-08 14:00:00.055849 | $1,894.00 | 1.395× | 0.852× | N | N | OPEN | OPEN | -14.78% mark | $0.01 | UNSETTLED | UNSETTLED |
| 242 | c77HBWuZG5HdZvdU8kmgGy37QSpjPaoNTnrMjJ3pump | 2026-08-08 14:30:00.040223 | $248,287.00 | 1.074× | 0.010× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.01 | $-0.00 | $0.00 |
| 243 | 2PAhsvKHcGqU7NoEgpMgxSsBZKDnLwXRwk5hKe3ypump | 2026-08-08 14:45:01.008543 | $139,062.00 | 1.319× | 0.401× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 244 | 9Jj9H3G4cLSjt73XZXcNAM9fN3PPYEYK2YDkkugJpump | 2026-08-08 14:45:01.008543 | $2,829.00 | 1.028× | 0.609× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 245 | BbgzeSgVegw2riMS8gjek2SWbpCpch6hifyK6pUpump | 2026-08-08 14:45:01.008543 | $1,282,995.00 | 1.401× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 246 | QbrVGRiGDvNbdtsaS1EfA1w1Mu97NZPGVGovo2Fpump | 2026-08-08 15:30:00.042216 | $1,512.00 | 1.000× | 1.000× | N | N | OPEN | OPEN | 0.00% mark | $0.00 | UNSETTLED | UNSETTLED |
| 247 | 9imhB1nbwRQ2c6Cf6Zz6zUdjPjNsWBatpug1ZtxibEWz | 2026-08-08 15:45:03.933518 | $1,760,941.00 | 2.645× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 248 | BPjiqnko1sooBvhrTnDxV4bKf7V5Qws9MbYRWDw8pump | 2026-08-08 16:15:01.102215 | $246,628.00 | 0.973× | 0.252× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 249 | BVxz4g44d7z2CV5ZERPsvxY3QznPmof1Ddpascjipump | 2026-08-08 16:15:01.102215 | $114,810.00 | 1.290× | 0.066× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 250 | FDAbdGm5mosDFZBHPmnjFTmfRGznaato2ZNrEu3pump | 2026-08-08 17:00:00.046930 | $155,610.00 | 1.363× | 0.010× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 251 | 49jXi3pCKpsJFjp2KVhHzyzesPktPBDscL6JooKvpump | 2026-08-08 17:15:00.222495 | $2,080.00 | 6.585× | 0.777× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 252 | DVCquhjj3wi93hc8HJE7WL8tAKCVmtHiMXD3Zpwgpump | 2026-08-08 17:15:00.222495 | $14,009.00 | 1.465× | 0.121× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 253 | BBkjUWoCQLqrxdnJ5h6gtpQFMdka8eEKoDmBFejApump | 2026-08-08 17:30:00.068162 | $2,556.00 | 1.291× | 0.568× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 254 | tQz8ucoP19hqbKynEZefpeVUwUiDCinLJYHrfRgpump | 2026-08-08 17:30:00.068162 | $5,594,944.00 | 1.117× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 255 | 9L3EmYg8ojsjXs1Lc1BGNSKjfNbQvk6d75tYy466pump | 2026-08-08 18:00:00.038942 | $42,093.00 | 2.286× | 0.038× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 256 | VHXEZvqstqZ9EBBUSboKnoxvmuRYy3p5Y5zfxbkpump | 2026-08-08 20:36:36.618396 | $1,234,536.00 | 1.562× | 0.002× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 257 | Au8wL7C2htCdn4mn3fZebDQYHa6xy6nSzuya9Brnpump | 2026-08-08 21:37:26.059017 | $58,663,627.00 | 1.081× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 258 | 4LwHKRgKHLvYtTqJRLHfdMydzis4dHfPvxW8TcYhpump | 2026-08-08 22:38:30.654859 | $2,490.00 | 3.962× | 0.739× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 259 | 39jq7BGb4UMNS57V8UH67b24QjroSmvyLnvFWkT5pump | 2026-08-08 23:39:57.605724 | $142,529.00 | 3.377× | 0.078× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 260 | 3ad2ZmAxqMw415yNC5AR9mC4UXE9nqWQv2ajVtdrpump | 2026-08-09 04:45:00.190016 | $2,094,524.00 | 1.492× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 261 | D6YvtVqMjeru8GeSMZ6w7jWcfe3ZnpaLVcaym3spump | 2026-08-09 04:45:00.190016 | $3,531,143.00 | 1.430× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 262 | 5QZDZtXwSHGfreiVwkLvhyLm9MN8APjEvEGzyArhpump | 2026-08-09 05:45:01.926339 | $10,740.00 | 1.687× | 0.597× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 263 | HkRvV6TfbGDnhbAaXctBfc8yfqWignizwakktB1Dpump | 2026-08-09 05:45:01.926339 | $1,386.00 | 1.013× | 0.985× | N | N | OPEN | OPEN | -1.52% mark | $0.00 | UNSETTLED | UNSETTLED |
| 264 | 4htjg3BekscJQsqjXvtCZZqJTnkNJnNvGE647V4opump | 2026-08-09 06:30:00.144184 | $220,768.00 | 3.622× | 0.008× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 265 | 8zB3BBW8x5YYDKtfkMEEyYWLLwaWYLAveTU66uEUpump | 2026-08-09 06:45:00.431895 | $86,164.00 | 2.221× | 0.028× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 266 | 4ABkahB3iu4EGiJTgbKMciKxfFCRzUP1BqvjUWzypump | 2026-08-09 08:30:00.045870 | $10,887.00 | 1.680× | 0.138× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 267 | BGBsxrYAt7SLUGXHY5gk1P1kScwfrYKgNsATt3v6pump | 2026-08-09 09:45:00.056553 | $29,569.00 | 1.005× | 0.068× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 268 | EKppz9JRQDVLhye12yc4T4P9ue7N6A4vVEB4uyvxpump | 2026-08-09 09:45:00.056553 | $48,006.00 | 3.840× | 0.191× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 269 | FYNohgbWFu2wNzq3195GjTYQ1vQjm1DjHjD1Zc5Kpump | 2026-08-09 10:00:02.886780 | $27,247.00 | 3.231× | 0.081× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 270 | gAMo6k933d3bi8BQhAFQaQRZJYWmBLBjdKaXzhApump | 2026-08-09 10:30:00.528435 | $3,124,346.00 | 1.441× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 271 | 3ctVkfsonbqvYXGs4Nw62afrvSc1FtWnEgnnVcBcpump | 2026-08-09 10:45:00.070473 | $11,436,041.00 | 1.872× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 272 | AahMPDKa7FRnRikC8r1G3BLJkfptE5afVJY5Cx9mpump | 2026-08-09 10:45:00.070473 | $54,428.00 | 1.033× | 0.031× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 273 | G8Gwet7J3Km8NRJVh6DqZCgWAw9JmYaZU39XQp6Wpump | 2026-08-09 10:45:00.070473 | $5,091.00 | 1.476× | 0.370× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 274 | GnD4MQEVmsYMgAMgT4w1Df4uSgssugi7buCZZwFjpump | 2026-08-09 11:15:00.067931 | $1,466.00 | 1.010× | 0.997× | N | N | OPEN | OPEN | -0.34% mark | $0.00 | UNSETTLED | UNSETTLED |
| 275 | fxvYpvzQuFxBKMJPp4RJsegiSU4x3a4M1vmbJTapump | 2026-08-09 11:15:00.067931 | $8,419,143.00 | 1.232× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 276 | 5CKuyx8kqzwHVZKoRMstBih9wteTv4XoSBq48j7Zpump | 2026-08-09 11:30:00.136965 | $42,199.00 | 2.282× | 0.040× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 277 | 3VshVuxnWQLevRL6YEWDLs8Zqicnj11tzPP5BgDXpump | 2026-08-09 11:45:00.195845 | $10,516,078.00 | 1.256× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 278 | C5Z3bf7AtthZLHcWueshpnZT7Nauv73oNzqcwKfWpump | 2026-08-09 12:30:00.418031 | $5,557,844.00 | 1.295× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 279 | Dz2iVSLXFp7dXowD1nybWyCXuUcpV7cBZu68YPV5pump | 2026-08-09 12:30:00.418031 | $156,154.00 | 2.474× | 0.150× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 280 | 9EDCzStHGJA8CMJY66hNaYifPqjotUr8ef28rNsmpump | 2026-08-09 13:30:02.358982 | $5,422,124.00 | 2.596× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 281 | 23EFHKdSYzpxGddyGUFFtLnsgf1toCg5Dg2Efegspump | 2026-08-09 13:45:00.134948 | $2,078.00 | 1.000× | 0.397× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 282 | 9w2nokGrjFACQaJaEJGafZgsxBePfDWdUav6ofSJpump | 2026-08-09 14:15:00.074366 | $68,186.00 | 3.258× | 0.054× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 283 | CSKgkXMem12u1yxc9s2UJrTaDiW3T6UmutyoRj8Apump | 2026-08-09 14:15:00.074366 | $2,942.00 | 72.493× | 1.000× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 284 | EgPGxfMqNnmxUT8NjipkzdG4BnCik8CTy6vMatxfpump | 2026-08-09 14:30:00.064387 | $10,294,836.00 | 1.671× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 285 | FM3Zhmqi7uQe6DUgWuiwRy7Wo3tR57A62frRHR48pump | 2026-08-09 14:30:00.064387 | $2,400.00 | 1.000× | 0.600× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 286 | V5uLMwv8PwHMbdYdeJY1mqEpBV7gMzBJxUVUD2rpump | 2026-08-09 14:30:00.064387 | $106,102,417.00 | 1.421× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 287 | BjbDYig3EfGdsdiFkAqjMHRNzKVLfLBdpmjC4eswpump | 2026-08-09 14:45:00.060587 | $23,624.00 | 8.550× | 0.609× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 288 | FJk5woeChLVbYM3AS1vGTmGoFv9batqchi3ECxF8pump | 2026-08-09 16:15:01.796153 | $20,028,710.00 | 1.002× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 289 | 9ZgtzJcmLNygrLjNCd55P62MacHBhnDoQ8Sve82HCxQr | 2026-08-09 16:30:00.116481 | $1,755,527.00 | 1.411× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 290 | D2dpyfSvamXjoLC3rui8zpVtEoXHoLq8qnPbhoq9pump | 2026-08-09 16:30:00.116481 | $2,809.00 | 1.000× | 0.855× | N | N | OPEN | OPEN | -14.52% mark | $0.00 | UNSETTLED | UNSETTLED |
| 291 | V7aZCNcVuToxmxQ1UGdSevDYcXoTtn9pF6xtgKfpump | 2026-08-09 16:45:00.017995 | $22,109,335.00 | 1.210× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 292 | CzevQmCSY6JxbToLBUkXgRcxDbuZHGhKehHTHfXnpump | 2026-08-09 17:00:00.199882 | $57,108.00 | 1.051× | 0.032× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 293 | X7XYwngwQXtkS1MwYuXix39oWLdmJDLgjTj9KuMpump | 2026-08-09 19:18:36.097027 | $120,660.00 | 1.028× | 0.012× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 294 | 9wmuKqhWXa7QgJN3JTYN7RV28htde8t2jnH9sCPhpump | 2026-08-09 19:19:00.772286 | $13,763,950.00 | 1.916× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 295 | 8NUjQ9szJ3vgmwMxv2Yx3dzJ6Gyd7kMoExULwDuEpump | 2026-08-10 02:46:01.950060 | $2,637.00 | 1.239× | 0.978× | N | N | OPEN | OPEN | 2.96% mark | $0.00 | UNSETTLED | UNSETTLED |
| 296 | 3fqify4QnaKFsvmFVqmLMUHaRKdiPki6w2H3GyDmpump | 2026-08-10 02:46:18.559193 | $402,052.00 | 0.987× | 0.033× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 297 | HXCDtzfeJNh7CnQRXXttWERuHLdceHmTE8E4pqsTpump | 2026-08-10 02:47:48.760390 | $1,394.00 | 1.011× | 1.000× | N | N | OPEN | OPEN | 1.15% mark | $0.00 | UNSETTLED | UNSETTLED |
| 298 | SFua2Htg4UzWCmnRvnBaQwg56VGjTJcRXiHmvZwpump | 2026-08-10 02:53:23.055104 | $285,390.00 | 1.103× | 0.011× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 299 | F7TGmpDqNFKxhHGCMcHDzoyxwkNtuX2d4aTZuEwwpump | 2026-08-10 03:03:05.167772 | $36,577.00 | 1.006× | 0.283× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 300 | Aa9RFpqf8ktzVsnuG9AeChzGf1CCGTbR1iQUQDpEpump | 2026-08-10 03:09:26.975183 | $3,926,824.00 | 1.047× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 301 | GbNntsciEuYSZH2fCcrxMQqfxS1KkDCQbPJySi7ipump | 2026-08-10 03:14:16.625666 | $7,380.00 | 2.008× | 0.251× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 302 | A13oRB9FFaiUjfi6LdCg6p9ka1u8SfGkUFs4SKvPpump | 2026-08-10 03:17:13.437104 | $9,159,054.00 | 2.271× | 0.761× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 303 | G5dyx7UfnX6TeHqrPVAM7qNMXznAsvjtbsbTCNbRpump | 2026-08-10 03:18:33.531768 | $123,521.00 | 1.574× | 0.196× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 304 | GQZhttWMZMYiDJ2NagTVn7qzzFoVx7M8MepvFzWHpump | 2026-08-10 03:19:14.478368 | $1,724.00 | 1.000× | 0.959× | N | N | OPEN | OPEN | -4.06% mark | $0.00 | UNSETTLED | UNSETTLED |
| 305 | FQ7udsp1xfPS6qRoNvt178mjeftTfqx1GUKWHyqCpump | 2026-08-10 03:19:57.093240 | $19,750.00 | 1.018× | 0.083× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 306 | 9Qdxj7dvvGsoWGuTVKZvSD4AoSVBLyB24kAt4AEmpump | 2026-08-10 03:21:15.695288 | $12,346.00 | 1.179× | 1.000× | N | N | OPEN | OPEN | 0.11% mark | $0.00 | UNSETTLED | UNSETTLED |
| 307 | EeB76LHyVZPMRvTpLcxJqqfSz4gg9f9XgsUmFybcpump | 2026-08-10 03:21:20.164884 | $1,113,226.00 | 1.381× | 0.305× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 308 | ALPv7UakCA8pdPGQJcNFmJ24sp7eRCHxLeyGWVZUpump | 2026-08-10 03:21:27.335879 | $125,529.00 | 1.442× | 0.078× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 309 | 24JfohUFKzUymwnGiAEQg2GSE8ykeMRH6VmFv5xzpump | 2026-08-10 03:21:35.031849 | $2,817.00 | 1.055× | 0.978× | N | N | OPEN | OPEN | 0.60% mark | $0.00 | UNSETTLED | UNSETTLED |
| 310 | 2nDPWkc1uui2Ju7AjVg7gDJph9QStMaTn9d8ptM3pump | 2026-08-10 03:27:50.855696 | $19,995.00 | 1.670× | 0.096× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 311 | 96m8QVSrTqKzYw5seV4UUmc5E2dJFhT61XSFVmZLpump | 2026-08-10 05:55:03.091398 | $5,416.00 | 26.997× | 0.944× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 312 | 7AdpKBd6fK6KGVEB7V7Cf5HhGTBLxEapkTE6vsBnpump | 2026-08-10 05:57:58.982674 | $3,310.00 | 1.628× | 0.516× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 313 | 7Dk8hGm1tFz17yB7wcdtfFJ8cUxdSQt4UUMXEtg8pump | 2026-08-10 06:06:30.398539 | $45,103.00 | 1.149× | 0.042× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 314 | 24NVAnzaULU3NhCE1RaCwGJzRqBDicqWL2J6a2Ykpump | 2026-08-10 06:10:12.594421 | $96,702.00 | 2.535× | 0.015× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 315 | KjtqAySqDkgu2hM1R29tkoFC2PsoPqoL6pH71jypump | 2026-08-10 06:12:26.271477 | $16,786,608.00 | 1.004× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 316 | 12nDpgjZZf4VxaE2kEpMKiziTnxXHpEScbe9khgupump | 2026-08-10 07:15:24.000261 | $9,488,249.00 | 2.036× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 317 | FXoZh2m24V3pVrZnnm8A1rP8GztSfSATpiTQBbiCpump | 2026-08-10 09:01:47.219953 | $32,729.00 | 1.725× | 0.151× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 318 | Z5eMsbbmwszcccAKrER7JpPPYTJBEdyAMELrKkNpump | 2026-08-10 12:12:25.251323 | $670,057.00 | 1.033× | 0.002× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 319 | 5qBraqhZzDMjtZGE6HEs68yTjGGTVAbnaUNWxnj7pump | 2026-08-10 12:21:04.886307 | $2,488.00 | 1.135× | 0.610× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 320 | FBYLoMLrAnECwucQKToh8dSd9sB9SekNia11Bkpzfomo | 2026-08-10 12:35:47.849763 | $11,921.00 | 1.690× | 0.167× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 321 | 8b6VG32MpzYYhrb4Cs5dQpqFbBVbUyNSHjgin8SPRpae | 2026-08-10 12:48:56.262826 | $4,862.00 | 1.749× | 0.305× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 322 | A6W8TTasbGD5mG894fxUzWtPJXMJy1PqXy82rpxKpump | 2026-08-10 13:04:49.506860 | $52,756.00 | 1.114× | 0.564× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 323 | 7q8PvUhqdVMhJqo1jc79kYZtNDbPovC6emuuEA31pump | 2026-08-10 13:26:56.347824 | $28,734.00 | 1.107× | 0.220× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 324 | EnQaaZvNG1JQoFAc42psH3VQSgW618haP9qu5jzVpump | 2026-08-10 16:21:18.392392 | $3,122.00 | 1.000× | 0.598× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 325 | 67xmJC4zGwmiqFBW6d6Fu3o4vkGEHxs9KKixbHuBpump | 2026-08-10 16:24:03.738061 | $23,717.00 | 17.478× | 0.341× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 326 | HDX2EGULJYcXPhHmjAkSMTkzUnYyqCyGzyJXSgvPpump | 2026-08-10 16:30:22.514138 | $38,249.00 | 4.391× | 0.090× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 327 | 8vkwwtTapt2o2T4wgksywuRJURSWDs2EvET8DR5Bpump | 2026-08-10 16:30:33.040771 | $2,483.00 | 1.199× | 0.652× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 328 | PxHepvru24Kh3JM26jTog97BPWeQegLUvgWLYNGpump | 2026-08-10 16:39:33.823713 | $19,187.00 | 1.002× | 0.071× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 329 | DqAnmtR5Do7wm1odKLpidTG13D8SyfmvVJpcS1Vvpump | 2026-08-10 17:11:53.634616 | $2,116.00 | 1.055× | 0.779× | N | N | OPEN | OPEN | -21.50% mark | $0.00 | UNSETTLED | UNSETTLED |
| 330 | 8TJt53kNbGRVu9J8g2vbD2Eiba1a1bnbCbtVJ3Xkpump | 2026-08-10 17:13:28.643622 | $1,820.00 | 1.010× | 0.847× | N | N | OPEN | OPEN | -15.33% mark | $0.00 | UNSETTLED | UNSETTLED |
| 331 | EAdCNaa8kjUrPzX8MAZEEhfNTfunmCHxbP7z2JZEpump | 2026-08-10 17:44:03.833321 | $2,067.00 | 17.878× | 1.032× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 332 | 5xZg9qVFiSZkyzufUoqXg3h659z36eUCn2JqPeAEpump | 2026-08-10 18:59:27.540001 | $2,521.00 | 2.612× | 0.664× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 333 | SAKtXn9BW77yukhAfaQsyoJpd6nZCieUpXUcHskpump | 2026-08-11 04:00:00.494335 | $889,405.00 | 2.180× | 0.002× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 334 | gWCnJhaLvQTreWGmWUr31MbFr31Wpm5RjAWAnt4pump | 2026-08-11 04:02:18.491949 | $4,703,742.00 | 1.002× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 335 | 7bfCYSDYFibjw5aFX9p9yCdS7gDKV5CmJQYc6jCepump | 2026-08-11 04:33:45.420351 | $8,451.00 | 3.332× | 0.165× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 336 | Bxj6sJzDgYXD348JzULmwvXb2UCjem1z6ero3BmwaoNT | 2026-08-11 05:43:45.674440 | $6,715.00 | 2.457× | 0.278× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 337 | 9A5QWVQuNSHWQsxi1w1dAZ8yAr9RbMsdpkGXMNt3pump | 2026-08-11 05:52:53.930877 | $140,187.00 | 1.324× | 0.019× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 338 | FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump | 2026-08-11 05:55:04.664267 | $674,332.00 | 1.655× | 0.262× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 339 | Hbdc16UwhkBJ4TCUK5HshFi6KXZmPKMdxL7scFpYpump | 2026-08-11 05:56:11.747937 | $14,412.00 | 1.000× | 0.116× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 340 | FPa8JsCeNM1YPayMc6kSAK86vdcPNwESTbzX6cgvpump | 2026-08-11 05:57:32.044189 | $17,070.00 | 1.851× | 0.123× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 341 | CFASPx9Fp95FQdxydtDxFWgL8g5PavDgcNaamZmdpump | 2026-08-11 05:57:46.552098 | $6,997.00 | 1.061× | 0.489× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 342 | 94s1DHtdinFRu8fabQY7muznn4bxC9FjxDhmMpjPpump | 2026-08-11 05:58:32.333481 | $15,616.00 | 1.346× | 0.171× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 343 | FKyBKC3795oqVnY1Q93BcvgU7FaAz9rY5nHizZdqpump | 2026-08-11 07:40:44.439004 | $2,632.00 | 1.000× | 0.580× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 344 | x5DTAdiLYDGZ7qDUCFzdEGidYqSV95ofy1G3Dhzpump | 2026-08-11 08:44:29.718186 | $4,896,844.00 | 1.132× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 345 | DrsSQuG2A2VyWsmLhxUnDLpGHi6yvSQ2yge73rLopump | 2026-08-11 10:20:34.112529 | $10,011,193.00 | 1.617× | 0.000× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 346 | 6Lc4HdkoJCQqU7hoV1vKHsgwSWFyoHHr84pfpbCrpump | 2026-08-11 10:32:44.320084 | $15,853.00 | 1.356× | 0.097× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 347 | BcygeEfTGeY8rXJ91i8GsM1nWgezsjMWrjqfgYd7pump | 2026-08-11 10:54:26.685091 | $23,775.00 | 0.961× | 0.061× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 348 | JAKnM5B8pC7747QqGEGyeJmdAn55mmjb2Eqd2bpSpump | 2026-08-11 10:55:13.911993 | $18,976.00 | 1.274× | 0.095× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 349 | AaXXFmEtfowS9fMomUibZoxmz8sZSmUgxG6By3Sepump | 2026-08-11 10:59:02.924906 | $3,527.00 | 1.320× | 0.428× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 350 | vvRpg4mfTALSVCCacdQSE8rvbn7dUsUhcWKD5KQpump | 2026-08-11 13:20:09.870001 | $39,592.00 | 1.118× | 0.106× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 351 | YzrX5ACNemBRPgj5xyWhL9XBDayv7D428GSC1aBpump | 2026-08-11 14:58:19.745171 | $2,265.00 | 1.472× | 0.824× | N | N | OPEN | OPEN | -17.62% mark | $0.00 | UNSETTLED | UNSETTLED |
| 352 | 8f6FXoXtKE4hnNGFzxM7Xh9TrUUVnWqvN4EWANwLpump | 2026-08-11 15:08:06.880206 | $10,076.00 | 2.050× | 0.251× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 353 | FugaEJGreRgnoCniRtRMj969LvbXS5T5b4qXUhnApump | 2026-08-11 15:35:14.911677 | $4,161.00 | 1.491× | 0.400× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 354 | D6D86WfHuviN4Sra4uvMGHkedtEHCC893krgntGjpump | 2026-08-11 16:43:21.818206 | $18,315.00 | 1.015× | 0.278× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 355 | DfmUxZaGKH46tY2YgL5YLbQXg5FKup6Ftf666Ea5pump | 2026-08-11 17:24:37.352053 | $3,026.00 | 1.080× | 0.988× | N | N | OPEN | OPEN | -0.26% mark | $0.00 | UNSETTLED | UNSETTLED |
| 356 | nbTMnY7TgnLYFpo2BSBJzFc8Ut2uhiJ5wqbqgG1pump | 2026-08-11 17:29:54.621800 | $44,141.00 | 1.063× | 0.036× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 357 | C6KwzgqzumjGSyV4WquUXuGWQQiZKgJBdiZ6evs4pump | 2026-08-11 17:33:50.524630 | $11,920.00 | 1.006× | 0.155× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 358 | 6HjvVo8yHNR4fLH3E2fXDACPvsc8mAtuuRRJagmQpump | 2026-08-12 05:53:11.108189 | $12,561.00 | 5.481× | 0.152× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 359 | nokrK27iKrZfPc9Vg5rwGvcVRuDdoYupLdvbYKQpump | 2026-08-12 06:21:32.205012 | $2,193,002.00 | 1.686× | 0.001× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 360 | 23e4CNuJxvBQ7RjNLc8Bh3yN3pQq6jeiTbyzJGXYPgme | 2026-08-12 07:25:58.575217 | $443,187.00 | 1.000× | 0.368× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 361 | ApMrbYXQk1j3GV62HnQLR2BPiH8MzAi5ywaW2MYxpump | 2026-08-12 08:39:15.123298 | $262,527.00 | 1.107× | 0.026× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 362 | vNn1usZo9ZmBMYfzZMtriw7rPJvpe2csN5mggWepump | 2026-08-12 12:18:54.529904 | $2,193,607.00 | 1.422× | 0.001× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 363 | BjDgfWnYP8emvpzkXH6GyksKdMfVrwsUQ5GZCBWpump | 2026-08-12 17:28:04.674665 | $2,143.00 | 1.011× | 0.881× | N | N | OPEN | OPEN | -10.69% mark | $0.00 | UNSETTLED | UNSETTLED |
| 364 | E5iDD4kt9gDxTaAeoCNeN3CcZAWB7FvbPXwqJuuHpump | 2026-08-12 21:43:18.208813 | $15,722.00 | 1.778× | 1.000× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 365 | EUB1eZBt4m3X4FbperWnKGJdvLsuLMu2YmJix5yjpump | 2026-08-13 07:35:24.714235 | $506,829.00 | 5.148× | 0.266× | Y | Y | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 366 | PrkyDdnE9A99ghintXqgoynRahwz4oevixigZg3pump | 2026-08-13 08:21:57.736080 | $20,633.00 | 3.846× | 1.000× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 367 | Gj3GbnLV8SU1VfjfepYB6obR1kz4RxNYyQP1ChQ5pump | 2026-08-13 08:26:18.047395 | $4,708.00 | 1.023× | 0.639× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 368 | 8TfggLjCG1ba17nBAjASVnRaWgwxaRaMmZZkXcy2pump | 2026-08-13 09:46:50.058710 | $15,987.00 | 1.706× | 0.819× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 369 | 635ceMMkJkzQvTyGsK3LdSzwokWTQ6CK4YUkh7fbpump | 2026-08-13 17:18:44.248759 | $3,164.00 | 1.860× | 0.962× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 370 | uknqkELeheL2w9buTQmdS1ERvysDy2n61XsULZgpump | 2026-08-14 14:19:05.230721 | $17,523,825.00 | 1.120× | 0.000× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 371 | BWGSjZ2QFg67u2GDUHcx2TtgrEjA3WoDdSoFMxWZpump | 2026-08-15 05:23:21.433003 | $13,925.00 | 1.031× | 0.702× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 372 | 2wMTr4ZttVr5tmS4wLStee59wi8f9QQfMtT2Hoispump | 2026-08-15 05:58:02.822257 | $23,433.00 | 1.882× | 0.842× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 373 | 3aNgeLpvxfEw82vyuJYzpZQTrhgJ2JPcn3L32EEdpump | 2026-08-15 06:01:25.010712 | $19,893.00 | 1.082× | 1.000× | N | N | OPEN | OPEN | 4.69% mark | $0.00 | UNSETTLED | UNSETTLED |
| 374 | EmrPLLKdw4BuCdURMYcKpyWwmS79YYgGcnqQsoJepump | 2026-08-15 06:03:12.969717 | $32,889.00 | 1.415× | 0.982× | N | N | OPEN | OPEN | 41.55% mark | $0.00 | UNSETTLED | UNSETTLED |
| 375 | 4pPMzm15kP9ebaUCmS9rAkm9hyQ3E68VysrJKpzdpump | 2026-08-15 06:07:47.798492 | $21,015.00 | 1.088× | 0.546× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 376 | ENGNF2NEz9EmgW2pGr1vSJHbuSDG183pQ6VnKnGcpump | 2026-08-15 06:13:14.616547 | $14,902.00 | 1.301× | 0.930× | N | N | OPEN | OPEN | 30.14% mark | $0.00 | UNSETTLED | UNSETTLED |
| 377 | FDQVxioVjKS6pTbfCa25qycBxA4ccXKN6BiN8ogtpump | 2026-08-15 06:30:15.550141 | $15,706.00 | 1.633× | 0.909× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 378 | CiW15o3Ei75uzBECgkbNzhfCVA38MeAPon3dJ2Mspump | 2026-08-15 06:32:02.577398 | $80,849.00 | 1.093× | 0.630× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 379 | CnVFr8iwHe3hM1wAzbSjoT7qgCiJ3p85hNkSJiU5pump | 2026-08-15 06:33:35.805419 | $9,227.00 | 1.246× | 0.467× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 380 | 2UhgCt25pWc6xgPrS2yFXVCVRfZhdVeqsF5nrH3Ppump | 2026-08-15 06:34:23.003386 | $11,840.00 | 1.000× | 0.548× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 381 | AkyVXqKQ6V6qpqNo7RBfGzyRCKp42fWgCtgeR4s2pump | 2026-08-15 06:34:23.003386 | $90,121.00 | 3.524× | 0.678× | Y | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 382 | C9pwLoWBU4XSNS5TFMyLUTzWVkJ2b2SoYywQy282pump | 2026-08-15 06:35:47.408254 | $15,869.00 | 1.049× | 1.000× | N | N | OPEN | OPEN | 2.68% mark | $0.00 | UNSETTLED | UNSETTLED |
| 383 | 2UzEQXxFr7yegPXBB49TZ3c8bnDNrjbYfzsXoBr3pump | 2026-08-15 06:37:47.013127 | $39,594.00 | 1.175× | 0.756× | N | N | OPEN | OPEN | -18.36% mark | $0.00 | UNSETTLED | UNSETTLED |
| 384 | Fbv6deLeJZdeRN1JTiR6BBZas4az6XKyoiL5nLYwpump | 2026-08-15 06:37:47.013127 | $11,063.00 | 1.025× | 0.654× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 385 | J7ePNotqozFqwxWXmsHezWyQUnHBnqtriRgrX76fpump | 2026-08-15 07:05:25.400583 | $29,744.00 | 1.296× | 0.885× | N | N | OPEN | OPEN | 29.63% mark | $0.00 | UNSETTLED | UNSETTLED |
| 386 | HhyWRxveftUw1k1BMxH5ZDyWTfEhkidnirFGtadApump | 2026-08-15 11:27:04.064725 | $3,519.00 | 1.049× | 0.849× | N | N | OPEN | OPEN | -15.12% mark | $0.00 | UNSETTLED | UNSETTLED |
| 387 | GiWxfFzr9Dsjm5BmWNQNn9mrQykPbchd4xx1CfTpump | 2026-08-15 12:37:35.616692 | $40,265.00 | 2.143× | 0.755× | Y | N | TAKE_PROFIT | TAKE_PROFIT | 50.00% | $0.00 | $0.00 | $0.00 |
| 388 | JoPyNAbrtVFeHq59U72GUAajnhSn1K6wFha62jL76UL | 2026-08-15 13:53:19.439688 | $9,275.00 | 1.041× | 0.623× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 389 | 5JakaEojY4Ln691yDVcziX3LfXUaToM3vb1xcZUFpump | 2026-08-15 15:29:48.281119 | $28,227.00 | 1.459× | 0.648× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 390 | FTnzLJYFBKcmnvD2n4H1tGrvUPU3AAHSF7411Upcpump | 2026-08-15 15:54:05.355169 | $3,626.00 | 1.021× | 0.964× | N | N | OPEN | OPEN | -3.61% mark | $0.00 | UNSETTLED | UNSETTLED |
| 391 | EVENyZUkDDXDDXp1pYqybEHsyfRPJvEx3DnfjMgXpump | 2026-08-15 16:36:28.098506 | $16,492.00 | 1.099× | 0.712× | N | Y | STOP_LOSS | STOP_LOSS | -25.00% | $0.00 | $-0.00 | $0.00 |
| 392 | wsSiusqQeA75B58QMo6Uw9wsqgNX6iWD6X5vNJ4pump | 2026-08-15 17:36:45.696962 | $3,821.00 | 1.000× | 0.784× | N | N | OPEN | OPEN | -21.57% mark | $0.00 | UNSETTLED | UNSETTLED |

## Reproducibility notes

- Entry field: `radar_tokens.first_market_cap`, which is immutable at MEMESCOPE’s first detection.
- Time ordering field: `token_market_snapshots.captured_at > radar_tokens.first_detected_at`.
- Exit sample: first post-detection sample satisfying `market_cap >= entry × TP` or `market_cap <= entry × 0.75`.
- No fee/slippage run: threshold fill return of TP - 1 or -25%.
- Cost run: the same threshold fills, reduced by the existing 30-bp-per-side and observed-liquidity constant-product impact model.

