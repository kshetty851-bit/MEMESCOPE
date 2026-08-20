"use client";

import { Character, RigDefs, portraitViewBox } from "@/components/hq/character-rig";
import { CHARACTERS } from "@/lib/hq/characters";
import type { EmployeeId } from "@/lib/hq/employees";
import { EMPLOYEE_BY_ID } from "@/lib/hq/employees";

/**
 * A HEAD-AND-SHOULDERS OF THE SAME PERSON.
 *
 * Not a second illustration. It runs the same rig through the same layers and
 * crops to the head — so a character can never drift between the room and the
 * panel, and adding an eleventh employee needs no portrait work at all.
 *
 * The crop is done with `viewBox`, which costs nothing: the browser is drawing
 * the same paths, just showing less of them. That is the whole reason the rig
 * is vector and not a sprite sheet.
 *
 * Used by the employee panel and by the mobile cards, where the plan is
 * explicit that a miniature full-body isometric figure would be unreadable.
 */

interface PortraitProps {
  id: EmployeeId;
  size?: number;
  /**
   * How much of the person the crop shows.
   *
   * `head` is the original chip used beside dense text — the panel, the
   * mobile cards. `bust` shows head and upper body for surfaces where the
   * portrait *is* the content, like the homepage crew. Both are viewBox crops
   * of the identical rig: there is one drawing of each person, framed twice.
   */
  frame?: "head" | "bust";
}

export function Portrait({ id, size = 44, frame = "head" }: PortraitProps) {
  const character = CHARACTERS[id];
  const employee = EMPLOYEE_BY_ID.get(id);

  // The crop comes from the rig rather than from a constant here: the two used
  // to be maintained separately and drifted apart the first time the head size
  // changed, which cropped the hair off every portrait in the card stack.
  return (
    <svg
      className="hq-portrait"
      data-frame={frame}
      width={size}
      height={frame === "bust" ? Math.round(size * 1.12) : size}
      viewBox={portraitViewBox(character, frame)}
      role="img"
      aria-label={employee ? `${employee.name}, ${employee.role}` : id}
    >
      <RigDefs />
      <Character character={character} />
    </svg>
  );
}
