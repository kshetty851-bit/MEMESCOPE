"use client";

import { notFound } from "next/navigation";
import { useEffect, useState } from "react";

import { Character, RigDefs } from "@/components/hq/character-rig";
import { HqStage } from "@/components/hq/hq-stage";
import { useAmbient } from "@/components/hq/use-ambient";
import { useDayPhase, useHqMotion } from "@/components/hq/use-hq-env";
import { IdeasPanel } from "@/components/hq/ideas-panel";
import { UNKNOWN_HQ_STATE, deriveHqState } from "@/lib/hq/adapter";
import { CHARACTERS, type Emotion, type Pose } from "@/lib/hq/characters";

/**
 * DEV-ONLY: the room alone, with no backend and no alpha gate.
 *
 * `/hq` sits behind the dashboard layout, which awaits `/alpha/session` — so
 * with no API running it redirects, and the room cannot be looked at at all.
 * That is the right behaviour for the product and useless for verifying a
 * change to the furniture. Same pattern as `dev-qa/crew`, same reason: a
 * headless browser needs the thing being verified in the first viewport.
 *
 * ── `operational` MUST BE EMPTY HERE ────────────────────────────────────
 *
 * It is the list of people whose *real* state outranks ambient, so the
 * scheduler refuses an ambient routine to anyone in it
 * (`ambient-scheduler.ts`, "core && operational.has(id)"). The version of this
 * page on the Ghibli branch passed `EMPLOYEES.map(e => e.id)` — every single
 * employee — which suppresses ambient for the entire cast and parks the office
 * it was written to animate. `UNKNOWN_HQ_STATE.operational` is `[]`, because
 * nothing measured means nobody is busy, which is exactly right.
 *
 * This mounts the identical `HqStage` over the identical stylesheets, driven
 * by the real ambient scheduler, so the games corner and the walks it plays
 * here are the ones the product plays. What it cannot show is anything that
 * depends on a reading: every desk is `unknown`, which is exactly what the
 * office is supposed to look like when nothing has been measured.
 *
 * Not part of the product: production builds 404 it.
 */
export default function HqQaPage() {
  if (process.env.NODE_ENV === "production") notFound();
  // `?poses=1` draws the pose and emotion grid instead of the room. Both are
  // dev-only views of the same rig; a pose that looks wrong here looks wrong
  // in the office, and this one can be screenshotted deterministically.
  //
  // Read in an effect rather than inline. Reading `window.location` during
  // render makes the server and the client disagree about which view this is,
  // and Next reported exactly that as a hydration failure — the first version
  // of this page traded one console error for another.
  const [poses, setPoses] = useState(false);
  const [ideas, setIdeas] = useState(false);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    setPoses(q.has("poses"));
    setIdeas(q.has("ideas"));
  }, []);
  if (poses) return <PoseGrid />;
  if (ideas) return <IdeasPreview />;
  return <Room />;
}

const GAME_POSES: Pose[] = ["playing_table", "cue_shot", "cheering"];
const EMOTIONS: Emotion[] = ["neutral", "happy", "sad", "angry", "surprised", "smug", "tired"];

function PoseGrid() {
  return (
    <main style={{ padding: "1.5rem", background: "var(--color-bg)", color: "var(--color-ink)" }}>
      <svg width={1400} height={640} viewBox="0 0 1400 640">
        <RigDefs />
        {GAME_POSES.map((pose, i) => (
          <g key={pose} transform={`translate(${140 + i * 200}, 190) scale(1.7)`}>
            <Character character={CHARACTERS.byte} pose={pose} />
            <text x={0} y={40} textAnchor="middle" fontSize={9} fill="currentColor">
              {pose}
            </text>
          </g>
        ))}
        {EMOTIONS.map((emotion, i) => (
          <g key={emotion} transform={`translate(${120 + i * 180}, 500) scale(2.6)`}>
            <Character character={CHARACTERS.nova} pose="standing" emotion={emotion} />
            <text x={0} y={26} textAnchor="middle" fontSize={7} fill="currentColor">
              {emotion}
            </text>
          </g>
        ))}
      </svg>
    </main>
  );
}

function Room() {
  const motion = useHqMotion();
  const phase = useDayPhase();
  const ambient = useAmbient(motion, UNKNOWN_HQ_STATE.operational, UNKNOWN_HQ_STATE.activity, phase);
  return (
    <main style={{ padding: "1rem", background: "var(--color-bg)" }}>
      <HqStage
        focusedZone={null}
        onFocusZone={() => {}}
        onSelectEmployee={() => {}}
        density="full"
        state={UNKNOWN_HQ_STATE}
        frames={ambient.frames}
      />
    </main>
  );
}

/**
 * The ideas board over a hand-built reading, so it can be looked at without a
 * backend. The figures below are a *fixture*, not a claim: this route is
 * dev-only and 404s in production, and the panel itself derives everything it
 * shows from whatever state it is handed.
 */
function IdeasPreview() {
  const state = deriveHqState({
    operations: {
      data: {
        health: {
          disk: { status: "degraded", percent_used: 86, warning_percent: 80, critical_percent: 92, measured: true, detail: "" },
          redis: { component: "redis", status: "healthy", detail: "", latency_ms: 1, measured: true },
          database: { component: "database", status: "healthy", detail: "", latency_ms: 2, measured: true },
          worker: { status: "healthy", nodes: ["celery@a1"], replies: 1, measured: true, detail: "" },
          scheduler: { status: "healthy", last_beat: null, seconds_since_beat: 12, expected_within_seconds: 300, measured: true, detail: "" },
          queues: { status: "degraded", depths: { enrichment: 812, scoring: 140 }, total: 952, measured: true, detail: "" },
          labs: [
            { measured: true, detail: "", label: "Dex Lab", stale_pct: 61, minutes_since_decision: 74 },
          ],
          overall: "degraded",
          unmeasured: 0,
          environment: "dev",
          version: "0",
          observed_at: new Date().toISOString(),
        },
        incidents: [
          { code: "REQ-014", kind: "approval", component: "lab", severity: "critical", status: "awaiting_owner", autonomy: "red", agent: null, signature: "s", symptoms: {}, root_cause: null, owner_rationale: null, detected_at: new Date().toISOString(), resolved_at: null, actions: [] },
        ],
        recent: [],
        activity: [
          { at: new Date().toISOString(), agent: "patch", action: "lab.run_tick", autonomy: "green", reason: "", outcome: "failed", preconditions: {}, result: {}, verification: {} },
        ],
        allowlist: [
          { key: "worker.pool_restart", autonomy: "green", agent: "patch", summary: "", reversible: true },
          { key: "disk.run_retention", autonomy: "green", agent: "byte", summary: "", reversible: true },
        ],
        autonomy_enabled: true,
        invariants: {},
      } as never,
      observedAt: Date.now(),
    },
    now: Date.now(),
  });
  return (
    <main style={{ padding: "2rem", background: "var(--color-bg)", maxWidth: 760 }}>
      <IdeasPanel state={state} />
    </main>
  );
}
