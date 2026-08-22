"use client";

import { useState } from "react";

import { Portrait } from "@/components/hq/portrait";
import { CHARACTERS } from "@/lib/hq/characters";
import { EMPLOYEES, EMPLOYEE_BY_ID, type EmployeeId } from "@/lib/hq/employees";
import { ZONE_BY_ID } from "@/lib/hq/zones";
import { cn } from "@/lib/utils";

/**
 * MEET THE MEMESCOPE TEAM.
 *
 * ── THE SAME CAST, NOT A SECOND ONE ─────────────────────────────────────
 *
 * Every name, role, portrait and department here is read from
 * `lib/hq/employees` and `lib/hq/characters` — the same data the isometric
 * office draws from. There is no second roster and no marketing copy that can
 * drift: if Nova's title changes, it changes in one file and both surfaces
 * follow. That is the whole point of the section. A visitor meets the crew
 * here and then finds the *same* crew working inside HQ, and the two must
 * never disagree about who exists.
 *
 * The portraits are literally the office rig, cropped to the head. Not an
 * illustration set drawn to match — the rig itself, so a character cannot look
 * like one person on the homepage and another at their desk.
 *
 * ── NOVA IS BIGGER, AND THAT IS THE ONLY SPECIAL CASE ───────────────────
 *
 * She spans two columns and leads the grid. A CEO rendered identically to the
 * nine people reporting to her communicates the opposite of the org she runs,
 * and a badge saying "CEO" next to an identical card is a label rather than a
 * hierarchy. Size is the hierarchy.
 *
 * ── NOTHING HERE IS A CLAIM ─────────────────────────────────────────────
 *
 * No metrics, no counts, no status. This section is a cast list; the numbers
 * live in HQ where they are sourced and timestamped. A profile says what a
 * desk *watches*, never how well it is going.
 *
 * The roster grew to fourteen and this file did not have to change to follow
 * it — the grid maps `EMPLOYEES`, so a new desk appears here the moment it
 * appears in HQ. Only the lede's count is a literal, and that is the one thing
 * worth keeping a human in the loop on.
 */
export function Crew() {
  const [open, setOpen] = useState<EmployeeId | null>(null);
  const nova = EMPLOYEE_BY_ID.get("nova")!;
  const rest = EMPLOYEES.filter((employee) => employee.id !== "nova");

  return (
    <section className="crew" aria-labelledby="crew-heading">
      <div className="crew-head">
        <p className="crew-eyebrow">The crew</p>
        <h2 id="crew-heading" className="crew-title">
          Meet the MEMESCOPE team
        </h2>
        <p className="crew-lede">
          Thirteen specialists, one per subsystem, and one operator dedicated
          to a single experiment. Each is a desk you can open in HQ and watch
          working — the same characters, the same names, reading the same live
          evidence.
        </p>
      </div>

      <ul className="crew-grid">
        <CrewCard
          employee={nova}
          lead
          open={open === "nova"}
          onToggle={() => setOpen(open === "nova" ? null : "nova")}
        />
        {rest.map((employee) => (
          <CrewCard
            key={employee.id}
            employee={employee}
            open={open === employee.id}
            onToggle={() => setOpen(open === employee.id ? null : employee.id)}
          />
        ))}
      </ul>
    </section>
  );
}

function CrewCard({
  employee,
  lead = false,
  open,
  onToggle,
}: {
  employee: (typeof EMPLOYEES)[number];
  lead?: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const character = CHARACTERS[employee.id];
  const zone = ZONE_BY_ID.get(employee.zone)?.label ?? employee.zone;

  return (
    <li className={cn("crew-card", lead && "crew-card-lead", open && "crew-card-open")}>
      {/*
        A button rather than a card with a click handler: this expands a
        disclosure, and a keyboard reader needs to know that before they press
        it. `aria-expanded` is the whole reason the profile is inside the same
        element rather than a floating panel.
      */}
      <button
        type="button"
        className="crew-button"
        onClick={onToggle}
        aria-expanded={open}
        data-testid={`crew-${employee.id}`}
      >
        <span className="crew-portrait" style={{ ["--crew-tint" as string]: `var(--hq-${employee.palette})` }}>
          <Portrait id={employee.id} size={lead ? 128 : 92} frame="bust" />
        </span>
        <span className="crew-identity">
          <span className="crew-name">{employee.name}</span>
          <span className="crew-role">{employee.role}</span>
        </span>
        <span className="crew-chevron" aria-hidden="true">
          {open ? "–" : "+"}
        </span>
      </button>

      {open ? (
        <div className="crew-profile">
          <dl>
            <dt>What I do</dt>
            <dd>{employee.whatIDo}</dd>
            <dt>Department</dt>
            <dd>{zone}</dd>
            <dt>Works with</dt>
            <dd>
              {employee.worksWith
                .map((id) => EMPLOYEE_BY_ID.get(id)?.name ?? id)
                .join(" · ")}
            </dd>
          </dl>
          {/* The rig's own one-liner, which is the character's voice rather
              than their job. It is what makes them a person instead of a row. */}
          <p className="crew-line">{character.personalityLine}</p>
        </div>
      ) : null}
    </li>
  );
}

/**
 * The door into HQ.
 *
 * Placed immediately after the crew and nowhere else on the page. The section
 * above introduces ten people; this is the sentence that says they are not a
 * cast list — they are working, right now, and you can go and watch. Anywhere
 * else on the page it is just another button.
 */
export function EnterHq() {
  return (
    <section className="crew-cta">
      <p className="crew-cta-line">
        They are at their desks now, reading the same live evidence this page is.
      </p>
      <a className="crew-cta-button" href="/hq">
        Enter MEMESCOPE HQ
      </a>
    </section>
  );
}
