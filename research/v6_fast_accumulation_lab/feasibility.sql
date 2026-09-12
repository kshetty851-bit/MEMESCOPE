-- V6 FAST-ACCUMULATION LAB — feasibility measurements.  RESEARCH_ONLY.
--
-- Every figure in V6_FAST_ACCUMULATION_FINAL_REPORT.md comes from a query here.
-- Read-only: no DDL, no writes, nothing production depends on.
--
-- Run against PROD, never dev — a dev copy runs no collectors and would report
-- coverage gaps that are an artefact of the copy rather than of the archive:
--   ssh ubuntu@51.79.166.133 \
--     "docker exec -i memescope-postgres-1 psql -U memescope -d memescope" < feasibility.sql
--
-- Baseline run: 2026-09-12 ~17:05 UTC, git 489492a.

\echo '=== Q1  archive extent: the only source of bonding-curve progress ==='
SELECT 'grad_tokens'        AS t, count(*)::text, min(first_seen_at)::text, max(first_seen_at)::text FROM grad_tokens
UNION ALL SELECT 'grad_curve_samples', count(*)::text, min(ts)::text, max(ts)::text FROM grad_curve_samples
UNION ALL SELECT 'pruned (series deleted)', count(*)::text, '', '' FROM grad_tokens WHERE pruned_at IS NOT NULL
UNION ALL SELECT 'migrated', count(*)::text, '', '' FROM grad_tokens WHERE migrated_at IS NOT NULL;

\echo '=== Q2  the longer archive, and what it is missing ==='
SELECT 'token_curve_snapshots' AS t, count(*)::text, min(captured_at)::text, max(captured_at)::text FROM token_curve_snapshots
UNION ALL SELECT 'discovered_tokens', count(*)::text, min(created_at)::text, max(created_at)::text FROM discovered_tokens
UNION ALL SELECT 'token_market_snapshots', count(*)::text, min(captured_at)::text, max(captured_at)::text FROM token_market_snapshots;
-- token_market_snapshots reaches back 4 weeks and carries NO reserves: curve
-- progress is not derivable from it at any latency.  \d token_market_snapshots

\echo '=== Q3  observation latency on the longer archive (one week) ==='
-- The decision timestamp of the slowest config is 120s.  This asks how much of
-- the universe is observed at all by then.
WITH t AS (
  SELECT d.id, d.block_time,
         (SELECT min(s.captured_at) FROM token_market_snapshots s WHERE s.token_id = d.id) AS first_snap
  FROM discovered_tokens d
  WHERE d.created_at >= now() - interval '8 days' AND d.created_at < now() - interval '1 day'
    AND d.block_time IS NOT NULL
)
SELECT count(*) AS tokens,
       count(first_snap) AS with_any_snapshot,
       round(100.0*count(first_snap)/count(*),2) AS pct_with_snap,
       count(*) FILTER (WHERE first_snap - block_time <= interval '120 seconds') AS within_120s,
       round(100.0*count(*) FILTER (WHERE first_snap - block_time <= interval '120 seconds')/count(*),3) AS pct_120s,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY extract(epoch from (first_snap - block_time)))::int AS median_lat_s
FROM t;

\echo '=== Q4  eligible entries per config, last 24h ==='
-- Two of three hypothesis legs: curve threshold + elapsed window + initial mcap.
-- The Telegram leg is uncollected (see the report) and is not applied.
WITH tok AS (
  SELECT mint, first_seen_at FROM grad_tokens
  WHERE first_seen_at >= now() - interval '24 hours' AND pruned_at IS NULL
), ent AS (
  SELECT t.mint, s.progress_pct, s.market_cap_quote,
         extract(epoch from (s.ts - t.first_seen_at)) AS elapsed_s
  FROM tok t JOIN grad_curve_samples s ON s.mint = t.mint
)
SELECT (SELECT count(*) FROM tok) AS tokens_24h,
       count(DISTINCT mint) AS tokens_with_samples,
       count(DISTINCT mint) FILTER (WHERE progress_pct >= 10 AND elapsed_s <= 60)  AS f60_curve_time,
       count(DISTINCT mint) FILTER (WHERE progress_pct >= 10 AND elapsed_s <= 60  AND market_cap_quote > 30) AS f60_full,
       count(DISTINCT mint) FILTER (WHERE progress_pct >= 15 AND elapsed_s <= 90)  AS f90_curve_time,
       count(DISTINCT mint) FILTER (WHERE progress_pct >= 15 AND elapsed_s <= 90  AND market_cap_quote > 30) AS f90_full,
       count(DISTINCT mint) FILTER (WHERE progress_pct >= 20 AND elapsed_s <= 120) AS f120_curve_time,
       count(DISTINCT mint) FILTER (WHERE progress_pct >= 20 AND elapsed_s <= 120 AND market_cap_quote > 30) AS f120_full
FROM ent;

\echo '=== Q5a  is the 30-minute exit path observable at all?  (FAST-90) ==='
-- Coverage on the UNCLIPPED series: how far past entry the polling actually got.
-- Kept as its own query -- folding it into Q5b makes one CTE the planner handles
-- badly, and the two questions are separate anyway.
WITH tok AS (
  SELECT mint, first_seen_at FROM grad_tokens
  WHERE first_seen_at >= now() - interval '24 hours'
    AND first_seen_at <= now() - interval '45 minutes' AND pruned_at IS NULL
), entry AS (
  SELECT DISTINCT ON (t.mint) t.mint, s.ts AS entry_ts
  FROM tok t JOIN grad_curve_samples s ON s.mint = t.mint
  WHERE s.progress_pct >= 15 AND extract(epoch from (s.ts - t.first_seen_at)) <= 90
    AND s.market_cap_quote > 30
  ORDER BY t.mint, s.ts
), cov AS (
  SELECT e.mint, e.entry_ts, max(s.ts) AS last_ts,
         count(*) FILTER (WHERE s.ts > e.entry_ts) AS post_samples
  FROM entry e JOIN grad_curve_samples s ON s.mint = e.mint
  GROUP BY 1,2
)
SELECT count(*) AS entries,
       count(*) FILTER (WHERE last_ts >= entry_ts + interval '30 minutes') AS full_30min_path,
       round(100.0*count(*) FILTER (WHERE last_ts >= entry_ts + interval '30 minutes')/count(*),1) AS pct_full,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY extract(epoch from (last_ts-entry_ts))/60)::int AS median_cov_min,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY post_samples)::int AS median_post_samples
FROM cov;

\echo '=== Q5b  ...or does it resolve early?  TP / SL / graduation ==='
-- Being fair to the archive: a position need not run the full horizon if it
-- resolves first.  Price is the curve mid, v_quote/v_token -- this measures
-- OBSERVABILITY, not profitability: no fee and no slippage model is applied.
WITH tok AS (
  SELECT mint, first_seen_at FROM grad_tokens
  WHERE first_seen_at >= now() - interval '24 hours'
    AND first_seen_at <= now() - interval '45 minutes' AND pruned_at IS NULL
), entry AS (
  SELECT DISTINCT ON (t.mint) t.mint, s.ts AS entry_ts,
         (s.v_quote_reserves / NULLIF(s.v_token_reserves,0)) AS entry_px
  FROM tok t JOIN grad_curve_samples s ON s.mint = t.mint
  WHERE s.progress_pct >= 15 AND extract(epoch from (s.ts - t.first_seen_at)) <= 90
    AND s.market_cap_quote > 30 AND s.v_token_reserves > 0
  ORDER BY t.mint, s.ts
), path AS (
  SELECT e.mint, e.entry_ts, max(s.ts) AS last_in_window, bool_or(s.complete) AS graduated,
         max((s.v_quote_reserves / NULLIF(s.v_token_reserves,0)) / e.entry_px) AS mfe_mult,
         min((s.v_quote_reserves / NULLIF(s.v_token_reserves,0)) / e.entry_px) AS mae_mult
  FROM entry e JOIN grad_curve_samples s ON s.mint = e.mint
   AND s.ts > e.entry_ts AND s.ts <= e.entry_ts + interval '30 minutes' AND s.v_token_reserves > 0
  GROUP BY 1,2
)
SELECT count(*) AS entries_with_any_path,
       count(*) FILTER (WHERE mfe_mult >= 2.0) AS touched_tp,
       count(*) FILTER (WHERE mae_mult <= 0.6) AS touched_sl,
       count(*) FILTER (WHERE graduated) AS graduated,
       count(*) FILTER (WHERE mfe_mult >= 2.0 OR mae_mult <= 0.6 OR graduated) AS resolved_early,
       round(100.0*count(*) FILTER (WHERE mfe_mult >= 2.0 OR mae_mult <= 0.6 OR graduated)/count(*),1) AS pct_resolved_early
FROM path;
-- Total resolved = Q5b resolved_early UNION Q5a full_30min_path; the report's
-- 46.5% is that union.  Everything else is censored, and Q6 shows the censoring
-- is correlated with the outcome.

\echo '=== Q6  WHY the window closes — censoring is correlated with the outcome ==='
-- `evicted` drops the LOWEST-PROGRESS token when the 500-slot set fills, and
-- `silent` drops tokens whose reserves stopped moving.  Both remove tokens that
-- stopped accumulating, i.e. losers, which biases any measured PF upward.
SELECT coalesce(unsubscribe_reason,'(still watching)') AS reason, count(*),
       round(100.0*count(*)/sum(count(*)) OVER (),1) AS pct
FROM grad_tokens WHERE first_seen_at >= now() - interval '24 hours'
GROUP BY 1 ORDER BY 2 DESC;

\echo '=== Q7  Telegram leg: uncollected, but recoverable ==='
SELECT count(*) AS grad_mints_24h,
       count(d.metadata_uri) AS with_metadata_uri,
       round(100.0*count(d.metadata_uri)/count(*),1) AS pct_uri
FROM grad_tokens g LEFT JOIN discovered_tokens d ON d.mint_address = g.mint
WHERE g.first_seen_at >= now() - interval '24 hours';
