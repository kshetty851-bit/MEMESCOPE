import re

with open("frontend/src/components/paper/positions-table.tsx", "r") as f:
    content = f.read()

# Add durationLabel and formatEntered helper
helpers = """function formatEntered(dateStr: string): string {
  const d = new Date(dateStr);
  if (!Number.isFinite(d.getTime())) return "—";
  const day = d.toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
  const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  return `${day} · ${time}`;
}

function durationLabel(opened: string, closed: string | null, now: number): string {
  const o = new Date(opened).getTime();
  if (!Number.isFinite(o)) return "—";
  const end = closed ? new Date(closed).getTime() : now;
  if (!Number.isFinite(end)) return "—";
  
  const seconds = Math.max(0, (end - o) / 1000);
  const m = Math.floor(seconds / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  
  if (d > 0) return `${d}d ${h % 24}h`;
  if (h > 0) return `${h}h ${m % 60}m`;
  return `${m}m`;
}
"""
content = content.replace("export function PositionsTable", helpers + "\nexport function PositionsTable")

# Update table headers
old_headers = """            <th className="py-2 text-left font-medium">Token</th>
            <th className="py-2 text-right font-medium">Entry</th>
            <th className="py-2 text-right font-medium">Exit rule</th>
            <th className="py-2 text-right font-medium">
              {showingClosedTrades ? "Exit" : "Current"}
            </th>
            <th className="py-2 text-right font-medium">
              {showingClosedTrades ? "Gross return" : "Result"}
            </th>
            <th className="py-2 text-right font-medium">Peak</th>
            <th className="py-2 text-right font-medium">
              {showingClosedTrades ? "Gross P/L" : "P/L"}
            </th>
            {showingClosedTrades ? (
              <>
                <th className="py-2 text-right font-medium">Fees</th>
                <th className="py-2 text-right font-medium">Slippage</th>
                <th className="py-2 text-right font-medium">Net P/L</th>
              </>
            ) : null}
            <th className="py-2 text-right font-medium">Execution</th>
            <th className="py-2 text-right font-medium">Status</th>
            <th className="py-2 text-right font-medium">Quote</th>"""

new_headers = """            <th className="py-2 text-left font-medium">Token</th>
            <th className="py-2 text-right font-medium">Entry MCAP</th>
            <th className="py-2 text-right font-medium">Current MCAP</th>
            <th className="py-2 text-right font-medium">
              {showingClosedTrades ? "Gross P/L" : "P/L"}
            </th>
            <th className="py-2 text-right font-medium">Entered</th>
            <th className="py-2 text-right font-medium">Held</th>
            {showingClosedTrades ? (
              <>
                <th className="py-2 text-right font-medium">Fees</th>
                <th className="py-2 text-right font-medium">Slippage</th>
                <th className="py-2 text-right font-medium">Net P/L</th>
              </>
            ) : null}
            <th className="py-2 text-right font-medium">Status / Market</th>
            <th className="py-2 text-right font-medium">Exit rule / Info</th>"""

content = content.replace(old_headers, new_headers)

# Update row rendering
old_row = """                  <td className="py-2.5 pr-4">
                    <TokenIdentity
                      mint={position.mint_address}
                      name={position.name}
                      symbol={position.symbol}
                      imageUrl={position.image_url}
                      size="xs"
                      showMint={false}
                    />
                    <span className="ml-2 text-xs text-ink-3">
                      #{position.entry_rank} at entry
                    </span>
                  </td>
                  <Cell value={formatPrice(position.entry_price)} />
                  <Cell
                    value={
                      position.target_price && position.stop_price
                        ? `TP ${formatPrice(position.target_price)} / SL ${formatPrice(position.stop_price)}`
                        : position.trailing_activated_at
                          ? formatPrice(position.trailing_stop_price)
                          : position.trailing_activation_multiple
                            ? `Pending ${position.trailing_activation_multiple}x`
                            : null
                    }
                  />
                  <Cell value={formatPrice(position.current_price)} />
                  <Cell
                    value={pct(position.current_pct)}
                    tone={signTone(position.current_pct)}
                  />
                  <Cell value={pct(position.peak_pct)} tone="neutral" />
                  <Cell
                    value={usd(
                      closed
                        ? (position.gross_pnl_usd ?? position.pnl_usd)
                        : position.pnl_usd,
                    )}
                    tone={signTone(
                      closed
                        ? (position.gross_pnl_usd ?? position.pnl_usd)
                        : position.pnl_usd,
                    )}
                  />
                  {showingClosedTrades ? (
                    <>
                      <Cell
                        value={usd(position.fee_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                      <Cell
                        value={usd(position.slippage_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                      <Cell
                        value={usd(position.net_pnl_usd)}
                        tone={signTone(position.net_pnl_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                    </>
                  ) : null}
                  <td
                    className="py-2.5 text-right text-xs text-ink-3"
                    title={
                      position.exit_execution_fallback_reason ??
                      position.entry_execution_fallback_reason ??
                      position.exit_execution_route ??
                      position.entry_execution_route ??
                      undefined
                    }
                  >
                    {modelLabel(
                      closed
                        ? position.exit_execution_model_version
                        : position.entry_execution_model_version,
                    )}
                  </td>
                  <td className="py-2.5 text-right">
                    <span
                      className={cn(
                        "rounded-sm border px-1.5 py-0.5 text-label uppercase tracking-wide",
                        closed
                          ? "border-line bg-raised text-ink-3"
                          : "border-accent/25 bg-accent/[0.07] text-accent",
                      )}
                    >
                      {closed ? (exitLabel(position.exit_reason) ?? "Closed") : "Open"}
                    </span>
                  </td>
                  {/* An open position is marked to a stored reading, not to a
                      live quote. Saying when it was observed is the difference
                      between a mark and a claim. A closed trade settled at its
                      exit and shows nothing here — a finished result cannot go
                      stale. */}
                  <td className="py-2.5 text-right">
                    {closed ? (
                      <span className="text-xs text-ink-3">settled</span>
                    ) : position.current_price_at ? (
                      <div className="flex flex-col items-end gap-0.5">
                        <FreshnessLabel capturedAt={position.current_price_at} />
                        {position.last_market_check_at && (
                          <LastCheckLabel checkedAt={position.last_market_check_at} />
                        )}
                      </div>
                    ) : position.pricing_status === "unpriced" ? (
                      <UnpricedData />
                    ) : (
                      <NoRecentData />
                    )}
                  </td>"""

new_row = """                  <td className="py-2.5 pr-4">
                    <TokenIdentity
                      mint={position.mint_address}
                      name={position.name}
                      symbol={position.symbol}
                      imageUrl={position.image_url}
                      size="xs"
                      showMint={false}
                    />
                    <span className="ml-2 text-xs text-ink-3">
                      #{position.entry_rank} at entry
                    </span>
                  </td>
                  <Cell value={usd(position.entry_market_cap)} />
                  <Cell value={usd(position.current_market_cap)} />
                  <Cell
                    value={usd(
                      closed
                        ? (position.gross_pnl_usd ?? position.pnl_usd)
                        : position.pnl_usd,
                    )}
                    hint={position.current_pct ? pct(position.current_pct) : undefined}
                    tone={signTone(
                      closed
                        ? (position.gross_pnl_usd ?? position.pnl_usd)
                        : position.pnl_usd,
                    )}
                  />
                  <td className="py-2.5 text-right text-xs text-ink-3 tabular-nums">
                    {formatEntered(position.opened_at)}
                  </td>
                  <td className="py-2.5 text-right text-xs text-ink-3 tabular-nums">
                    <DurationLabel opened={position.opened_at} closed={position.closed_at} />
                  </td>
                  {showingClosedTrades ? (
                    <>
                      <Cell
                        value={usd(position.fee_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                      <Cell
                        value={usd(position.slippage_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                      <Cell
                        value={usd(position.net_pnl_usd)}
                        tone={signTone(position.net_pnl_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                    </>
                  ) : null}
                  <td className="py-2.5 text-right">
                    <div className="flex flex-col items-end gap-1">
                      <span
                        className={cn(
                          "rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                          closed
                            ? "border-line bg-raised text-ink-3"
                            : "border-accent/25 bg-accent/[0.07] text-accent",
                        )}
                      >
                        {closed ? (exitLabel(position.exit_reason) ?? "Closed") : "Open"}
                      </span>
                      {closed ? (
                        <span className="text-[10px] text-ink-3">settled</span>
                      ) : position.current_price_at ? (
                        <FreshnessLabel capturedAt={position.current_price_at} />
                      ) : position.pricing_status === "unpriced" ? (
                        <UnpricedData />
                      ) : (
                        <NoRecentData />
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 text-right text-xs">
                    <div className="flex flex-col items-end text-ink-3"
                        title={
                          position.exit_execution_fallback_reason ??
                          position.entry_execution_fallback_reason ??
                          position.exit_execution_route ??
                          position.entry_execution_route ??
                          undefined
                        }>
                      <span className="tabular-nums">
                      {
                        position.target_price && position.stop_price
                          ? `TP ${formatPrice(position.target_price)} / SL ${formatPrice(position.stop_price)}`
                          : position.trailing_activated_at
                            ? formatPrice(position.trailing_stop_price)
                            : position.trailing_activation_multiple
                              ? `Pending ${position.trailing_activation_multiple}x`
                              : "—"
                      }
                      </span>
                      <span className="text-[10px]">
                      {modelLabel(
                        closed
                          ? position.exit_execution_model_version
                          : position.entry_execution_model_version,
                      )}
                      </span>
                    </div>
                  </td>"""

content = content.replace(old_row, new_row)

duration_comp = """function DurationLabel({ opened, closed }: { opened: string; closed: string | null }) {
  const now = useSharedClock(60000); // 1-minute shared clock
  return <>{durationLabel(opened, closed, now)}</>;
}"""
content = content + "\n" + duration_comp

with open("frontend/src/components/paper/positions-table.tsx", "w") as f:
    f.write(content)
