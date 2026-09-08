with entry as (
  select distinct on (s.mint_address, date_trunc('hour', s.captured_at))
         s.mint_address, s.captured_at as t0, s.price_usd as p0
  from token_market_snapshots s
  join discovered_tokens d on d.mint_address = s.mint_address
  where s.captured_at >= timestamptz '2026-09-01 00:00Z'
    and s.captured_at <  timestamptz '2026-09-04 04:00Z'
    and s.price_usd > 0 and s.liquidity_usd >= 25000
    and s.trading_status = 'trading' and s.suspect is not true
    and d.source_program in ('6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',
                             'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA')
    and extract(minute from s.captured_at) < 10
  order by s.mint_address, date_trunc('hour', s.captured_at), s.captured_at
), path as (
  select e.mint_address, e.t0, e.p0,
    (select max(m.price_usd) from token_market_snapshots m
      where m.mint_address=e.mint_address and m.captured_at between e.t0 and e.t0+interval '6 hours'
        and m.trading_status='trading' and m.price_usd is not null) as peak,
    (select m.price_usd from token_market_snapshots m
      where m.mint_address=e.mint_address
        and m.captured_at between e.t0+interval '5 hours' and e.t0+interval '7 hours'
        and m.trading_status='trading' and m.price_usd is not null
      order by m.captured_at desc limit 1) as p_end,
    st.delisted_at
  from entry e left join token_enrichment_state st on st.mint_address=e.mint_address
), cls as (
  select
    case when delisted_at is not null and delisted_at < t0+interval '6 hours' then 0.0
         else least(peak/p0, 50) end as peak_mult,
    case when delisted_at is not null and delisted_at < t0+interval '6 hours' then 0.0
         when p_end is not null then least(p_end/p0, 50) else 0.0 end as end_mult
  from path where peak is not null or delisted_at is not null
), k(level) as (values (1.10),(1.25),(1.50),(2.00),(3.00),(5.00))
select k.level as take_profit_at,
  round(100.0*count(*) filter (where c.peak_mult >= k.level)/count(*)) as pct_filled,
  -- gross: fill at the level, else hold to the clock
  round((avg(case when c.peak_mult >= k.level then k.level else c.end_mult end) - 1)::numeric * 100, 1) as gross_pct,
  -- net of the platform's own execution model: ~60bps round trip plus slippage
  round(((avg(case when c.peak_mult >= k.level then k.level*0.985 else c.end_mult*0.985 end)) - 1)::numeric * 100, 1) as net_pct
from cls c cross join k
group by k.level order by k.level;
