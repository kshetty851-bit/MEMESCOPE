import { Absent } from "@/components/ui/num";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";

import { DataClassLabel, StatusPill, agoFromIso, humanize } from "./display";
import type { SourceHealth } from "./types";

/**
 * DATA HEALTH — one row per source.
 *
 * A disabled source (Reddit, X) is shown AS disabled with its reason. The
 * failure this panel exists to prevent is the empty row: a source that is off
 * and a source that is quiet look identical when both are blank.
 */
export function DataHealthPanel({
  sources,
  title = "Data health",
}: {
  sources: SourceHealth[];
  title?: string;
}) {
  return (
    <Panel density="flush">
      <PanelHeader className="mb-0 p-4 pb-3">
        <PanelTitle>{title}</PanelTitle>
      </PanelHeader>
      {sources.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-ink-3">No sources reported.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <caption className="sr-only">Collection status per data source</caption>
            <thead>
              <tr className="border-y border-line bg-sunken text-left text-label uppercase text-ink-3">
                <th scope="col" className="px-4 py-2 font-medium">Source</th>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
                <th scope="col" className="px-3 py-2 font-medium">Reason</th>
                <th scope="col" className="px-3 py-2 font-medium">Last run</th>
                <th scope="col" className="px-3 py-2 font-medium">Data class</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr
                  key={s.source}
                  data-testid={`source-${s.source}`}
                  className="border-b border-line-subtle"
                >
                  <th scope="row" className="px-4 py-2 text-left font-medium text-ink">
                    {s.label}
                  </th>
                  <td className="px-3 py-2">
                    <StatusPill status={s.status} />
                  </td>
                  <td className="px-3 py-2 text-ink-2">
                    {s.reason ? humanize(s.reason) : <Absent label="no reason reported" />}
                  </td>
                  <td className="px-3 py-2 text-ink-2" data-numeric>
                    {agoFromIso(s.last_run_at)}
                  </td>
                  <td className="px-3 py-2">
                    <DataClassLabel dataClass={s.data_class} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
