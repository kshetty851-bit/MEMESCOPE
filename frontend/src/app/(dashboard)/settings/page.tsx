"use client";

import { PageBody } from "@/components/layout/app-shell";
import { SegmentedControl } from "@/components/ui/filters";
import { Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";
import { useDisplayMode } from "@/hooks/use-display-mode";
import { useNavRail } from "@/hooks/use-nav-rail";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { useSpaceIntensity, type SpaceIntensity } from "@/hooks/use-space";
import { BUILD } from "@/lib/env";
import { cn } from "@/lib/utils";

/**
 * SETTINGS.
 *
 * Four preferences, and they are the four MEMESCOPE actually has. Each one is
 * already wired to something real: `data-mode`, `data-rail` and `data-space` on
 * the document element, all persisted in localStorage and all applied before
 * first paint by their boot scripts.
 *
 * What is deliberately absent: account, profile, notifications, alerts, API
 * keys, theme. None of those exist on the backend, and a settings page that
 * lists switches which do nothing is worse than a short one — it teaches the
 * user that controls here are decorative.
 *
 * So this is a small page. It is supposed to be.
 */

function Setting({
  title,
  description,
  control,
  note,
}: {
  title: string;
  description: string;
  control: React.ReactNode;
  note?: string;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-line-subtle py-4 first:pt-0 last:border-0 last:pb-0 md:flex-row md:items-start md:justify-between md:gap-8">
      <div className="min-w-0 max-w-md">
        <h3 className="text-sm font-medium text-ink">{title}</h3>
        <p className="mt-1 text-xs leading-relaxed text-ink-2">{description}</p>
        {note ? <p className="mt-1.5 text-xs leading-relaxed text-ink-3">{note}</p> : null}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

export default function SettingsPage() {
  const { mode, setMode } = useDisplayMode();
  const { state: rail, toggle: toggleRail } = useNavRail();
  const { intensity, set: setIntensity } = useSpaceIntensity();
  const reducedMotion = useReducedMotion();

  return (
    <PageBody width="prose" className="flex flex-col gap-5">
      <Toolbar
        eyebrow="Settings"
        title="Display"
        description="Everything here is a local preference, stored in this browser and applied before the page paints. MEMESCOPE has no account settings yet."
      />

      <Panel density="comfortable">
        <div className="flex flex-col">
          <Setting
            title="Density"
            description="Command mode strips ambient decoration and tightens spacing. Nothing is removed except ornament — every figure and control is present in both."
            control={
              <SegmentedControl
                label="Density"
                showLabel={false}
                size="md"
                options={[
                  { value: "full", label: "Full" },
                  { value: "compact", label: "Command" },
                ]}
                value={mode}
                onChange={(value) => setMode(value as "full" | "compact")}
              />
            }
          />

          <Setting
            title="Universe"
            description="How much of the MEMESCOPE space environment runs behind the terminal. It is decorative and sits below every surface — it never affects readability."
            note={
              intensity === "full"
                ? "Full: stars, nebulae, dust, and occasional meteors, satellites, rockets and a rare comet."
                : intensity === "minimal"
                  ? "Minimal: a still sky. No crossing objects."
                  : "Off: a flat canvas."
            }
            control={
              <SegmentedControl
                label="Universe"
                showLabel={false}
                size="md"
                options={[
                  { value: "full", label: "Full" },
                  { value: "minimal", label: "Minimal" },
                  { value: "off", label: "Off" },
                ]}
                value={intensity}
                onChange={(value) => setIntensity(value as SpaceIntensity)}
              />
            }
          />

          <Setting
            title="Navigation rail"
            description="Collapse the rail to icons to give the scanner another 160px of width."
            control={
              <SegmentedControl
                label="Navigation rail"
                showLabel={false}
                size="md"
                options={[
                  { value: "expanded", label: "Expanded" },
                  { value: "collapsed", label: "Collapsed" },
                ]}
                value={rail}
                onChange={() => toggleRail()}
              />
            }
          />

          <Setting
            title="Motion"
            description="Read from your operating system, not stored here. MEMESCOPE follows it automatically — with reduced motion on, every crossing object in the universe is removed and the sky holds still."
            control={
              <span
                className={cn(
                  "inline-flex h-8 items-center rounded-md border px-3 text-xs",
                  reducedMotion
                    ? "border-up/35 bg-up/10 text-up"
                    : "border-line-control text-ink-2",
                )}
              >
                {reducedMotion ? "Reduced motion on" : "System default"}
              </span>
            }
          />
        </div>
      </Panel>

      <Panel density="compact">
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-xs">
          <div className="flex items-baseline gap-2">
            <dt className="text-ink-3">Version</dt>
            <dd data-numeric className="text-ink-2">
              {BUILD.version}
            </dd>
          </div>
          <div className="flex items-baseline gap-2">
            <dt className="text-ink-3">Build</dt>
            <dd data-numeric className="text-ink-2">
              {BUILD.sha}
            </dd>
          </div>
          <div className="flex items-baseline gap-2">
            <dt className="text-ink-3">Environment</dt>
            <dd className="text-ink-2">{BUILD.environment}</dd>
          </div>
        </dl>
      </Panel>
    </PageBody>
  );
}
