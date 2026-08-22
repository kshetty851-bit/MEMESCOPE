"use client";

import "@/styles/characters.css";

import { SEATED_AWAY_POSES, STANDING_POSES } from "@/lib/hq/characters";
import type {
  Accessory,
  BodyType,
  CharacterDefinition,
  CharacterLook,
  HairStyle,
  HeadShape,
  Outfit,
  Pose,
} from "@/lib/hq/characters";
import type { EggId } from "@/lib/hq/ambient";

/**
 * THE CHARACTER RIG.
 *
 * One body, drawn from parts. Ten people are ten *compositions* of head shape,
 * build, hair, garment, accessory and posture — not ten drawings. That is the
 * difference between a cast that can grow and one where adding an eleventh
 * person means commissioning artwork.
 *
 * PROPORTIONS
 *
 * The reference draws roughly four heads to a body, which reads as a
 * children's game. These are about five and a half, which keeps the cartoon
 * warmth while letting the cast read as working adults — the room is mission
 * control, not a playroom.
 *
 * Characters face the camera in three-quarter view rather than being drawn per
 * isometric facing. Four facings would quadruple the rig for a room where
 * everyone sits at a fixed desk looking at a screen, and a person facing away
 * from the reader is a person the reader cannot identify.
 *
 * HOW THE PARTS ARE SHARED
 *
 * `<RigDefs/>` is rendered once per stage and holds the geometry that never
 * varies — the chair, the seated leg mass. Everything that *does* vary is a
 * small inline path, because a `<use>` of a shape that needs a different fill
 * per instance costs more in overrides than it saves in bytes.
 *
 * COORDINATE SPACE
 *
 * Origin is the floor at the character's feet, y negative upward, matching the
 * stage's tile anchors. A seated character occupies about 58 units, a standing
 * one about 72 — roughly 1.5× desk height, which is the ratio the reference
 * uses and the reason its offices read as inhabited rather than as furniture
 * showrooms.
 */

const SEATED_HIP_Y = -26;
const STANDING_HIP_Y = -34;

interface CharacterProps {
  /**
   * The visual definition. `CharacterLook` rather than the full employee
   * definition, because the rig also dresses the support staff — people the
   * office employs but the adapter has never heard of.
   */
  character: CharacterLook;
  /** Overrides `defaultPose`. Driven by the ambient scheduler. */
  pose?: Pose;
  /**
   * Forces the stance. The stage sets `standing` for anyone away from their own
   * desk: a chair does not follow you to the break room, and a seated figure
   * standing on open floor is the tell that a walk system was bolted on.
   * `lounge` is the third option the sofa finally made honest: seated, but on
   * furniture that already exists at the destination, so the rig draws legs
   * and no chair of its own.
   */
  stance?: "seated" | "standing" | "lounge";
  /** A rare, harmless flourish. Never operational. */
  egg?: EggId;
}

/** Shared geometry, rendered once per SVG document. */
export function RigDefs() {
  return (
    <defs>
      {/* A real office chair: a padded seat, a tall back that shows either side
          of a seated figure, and a chrome stem on a star base. The old one was
          a near-black wedge the same value as the floor, so ten people
          appeared to be sitting on nothing at all. */}
      <symbol id="hq-chair" viewBox="-24 -40 48 52">
        <path className="hq-chair-back" d="M-14 -4 L14 -4 L13 -30 Q13 -36 7 -36 L-7 -36 Q-13 -36 -13 -30 Z" />
        <path className="hq-chair" d="M-17 9 L17 9 L15 -4 L-15 -4 Z" />
        <path className="hq-chair" d="M-17 9 L17 9 L16 12 L-16 12 Z" opacity="0.75" />
        <path className="hq-chair-stem" d="M-2.5 12 L2.5 12 L3.5 19 L-3.5 19 Z" />
        <path className="hq-chair-stem" d="M-11 22 L11 22 L13 24 L-13 24 Z" />
      </symbol>

      <symbol id="hq-seated-legs" viewBox="-18 -6 36 30">
        <path className="hq-legs" d="M-11 -6 L11 -6 L13 10 L-13 10 Z" />
        <path className="hq-legs-shadow" d="M-13 10 L13 10 L11 18 L-11 18 Z" />
      </symbol>

      {/* Sitting on a sofa or a conference chair: thighs toward the camera,
          shins dropping to visible feet. The pose HQ-3 deferred because faking
          it — hiding half the body behind the sofa — was the one trick the
          shared-rig rule exists to forbid. */}
      <symbol id="hq-lounge-legs" viewBox="-16 -6 32 34">
        <path className="hq-legs" d="M-11 -6 L11 -6 L14 6 L12 9 L-12 9 L-14 6 Z" />
        <path className="hq-legs" d="M-11 8 L-4 8 L-4 22 L-11 22 Z" />
        <path className="hq-legs" d="M4 8 L11 8 L11 22 L4 22 Z" />
        <path className="hq-shoe" d="M-12 22 L-3.5 22 L-3 26.5 Q-3 28 -6 28 L-11 28 Q-13 28 -12.5 25 Z" />
        <path className="hq-shoe" d="M3.5 22 L12 22 L12.5 25 Q13 28 11 28 L6 28 Q3 28 3 26.5 Z" />
      </symbol>

      <symbol id="hq-standing-legs" viewBox="-14 -4 28 42">
        <path className="hq-legs" d="M-9 -4 L9 -4 L11 30 L4 30 L2 6 L-2 6 L-4 30 L-11 30 Z" />
        {/* Feet. Without them a standing figure looks pinned to the floor
            rather than stood on it, and every walk reads as a glide. */}
        <path className="hq-shoe" d="M-11.5 30 L-3.5 30 L-3 36 Q-3 38 -6 38 L-11 38 Q-13 38 -12.5 35 Z" />
        <path className="hq-shoe" d="M3.5 30 L11.5 30 L12.5 35 Q13 38 11 38 L6 38 Q3 38 3 36 Z" />
      </symbol>
    </defs>
  );
}

export function Character({ character, pose, stance, egg }: CharacterProps) {
  const active = pose ?? character.defaultPose;
  const mode: "seated" | "standing" | "lounge" =
    stance ??
    (STANDING_POSES.has(active)
      ? "standing"
      : SEATED_AWAY_POSES.has(active)
        ? "lounge"
        : "seated");
  const standing = mode === "standing";
  const hipY = standing ? STANDING_HIP_Y : SEATED_HIP_Y;
  const build = BUILD[character.bodyType];
  const shoulderY = hipY - build.torsoHeight;
  const headY = shoulderY - build.neck - HEAD.radius;

  return (
    <g
      className="hq-character"
      data-body={character.bodyType}
      data-pose={active}
      data-stance={mode}
      data-egg={egg}
      style={
        {
          "--hq-skin": `var(--hq-skin-${character.skinTone})`,
          "--hq-hair": `var(--hq-hair-${character.hairTone})`,
          "--hq-garment": `var(--hq-${character.palette})`,
        } as React.CSSProperties
      }
    >
      {/* Contact shadow. Grounds the figure so it does not float above the
          floor plate — the single cheapest thing that makes an isometric scene
          look inhabited. */}
      <ellipse className="hq-contact-shadow" cx={0} cy={2} rx={build.shoulder + 4} ry={5} />

      {/* The chair belongs to the desk stance only. Lounging happens on
          furniture that is already drawn at the destination — the sofa, a
          conference chair — and a second chair materialising under someone
          was exactly the fake this stance exists to avoid. */}
      {mode === "seated" ? <use href="#hq-chair" x={-24} y={hipY - 12} width={48} height={52} /> : null}

      {standing ? (
        <use href="#hq-standing-legs" x={-14} y={hipY - 4} width={28} height={42} />
      ) : mode === "lounge" ? (
        <use href="#hq-lounge-legs" x={-16} y={hipY - 6} width={32} height={34} />
      ) : (
        <use href="#hq-seated-legs" x={-18} y={hipY - 6} width={36} height={30} />
      )}

      <Torso build={build} hipY={hipY} shoulderY={shoulderY} />
      <Garment outfit={character.outfit} build={build} shoulderY={shoulderY} hipY={hipY} />
      <Arms pose={active} build={build} shoulderY={shoulderY} />

      {/* Neck, then head, then hair — painted in that order so hair overlaps
          the skull rather than being clipped by it. */}
      <rect
        className="hq-skin"
        x={-4}
        y={shoulderY - build.neck}
        width={8}
        height={build.neck + 2}
        rx={3}
      />
      <Head shape={character.headShape} y={headY} />
      <Face y={headY} pose={active} egg={egg} />
      <Hair style={character.hair} shape={character.headShape} y={headY} />

      <AccessoryPart accessory={character.accessory} pose={active} shoulderY={shoulderY} />
      {egg === "telescope" ? <Telescope shoulderY={shoulderY} /> : null}
    </g>
  );
}

/* ---------------------------------------------------------------------- */

interface Build {
  shoulder: number;
  hip: number;
  torsoHeight: number;
  neck: number;
}

/**
 * Four builds, and they are genuinely different shapes rather than scales.
 * `broad` has square shoulders and a short neck; `tall` is narrow with a long
 * one. At 64px those silhouettes are still distinguishable, which is the whole
 * requirement.
 */
const BUILD: Record<BodyType, Build> = {
  slim: { shoulder: 11, hip: 9, torsoHeight: 22, neck: 5 },
  broad: { shoulder: 15, hip: 12, torsoHeight: 20, neck: 3 },
  tall: { shoulder: 11, hip: 10, torsoHeight: 26, neck: 6 },
  compact: { shoulder: 13, hip: 11, torsoHeight: 17, neck: 4 },
};

/**
 * Head size.
 *
 * Ten rather than nine, which lands the cast at roughly four and a half heads
 * tall. That is the management-game proportion the reference uses, and it is
 * also the smallest head that can carry a readable face at the size a desk is
 * drawn: at nine, two eyes and a mouth were three grey pixels.
 */
const HEAD = { radius: 10 };

/** Hand radius. Deliberately generous — see the typing branch in `Arms`. */
const HAND = 2.7;

/**
 * Where this character's head actually is, and how to frame it.
 *
 * The portrait used to hardcode two crop offsets, one for standing and one for
 * seated. They were correct for exactly the proportions the rig had on the day
 * they were written, and the moment the head grew by a unit every portrait
 * started clipping the top of somebody's hair.
 *
 * Deriving the crop from the same constants that place the head means the two
 * can never disagree again — a proportion change carries the framing with it.
 */
export function portraitViewBox(
  character: CharacterDefinition,
  frame: "head" | "bust" = "head",
): string {
  const standing = STANDING_POSES.has(character.defaultPose);
  const build = BUILD[character.bodyType];
  const hipY = standing ? STANDING_HIP_Y : SEATED_HIP_Y;
  const headY = hipY - build.torsoHeight - build.neck - HEAD.radius;
  if (frame === "bust") {
    // Head and upper body: air above the hair, down through most of the
    // torso, wide enough for the widest shoulders plus a raised arm. Sized
    // from the same build constants as the figure itself, so a rig proportion
    // change re-frames every portrait rather than beheading them — the exact
    // failure the head crop's comment already records.
    const top = headY - HEAD.radius - 8;
    const bottom = hipY - build.torsoHeight * 0.15;
    const height = bottom - top;
    const width = Math.max(build.shoulder * 2 + 18, height * 0.92);
    return `${-width / 2} ${top} ${width} ${height}`;
  }
  // A head-and-shoulders: a little air above the hair, down to the collarbone.
  const top = headY - HEAD.radius - 7;
  const size = HEAD.radius * 2 + 22;
  return `${-size / 2} ${top} ${size} ${size}`;
}

function Torso({ build, hipY, shoulderY }: { build: Build; hipY: number; shoulderY: number }) {
  return (
    <path
      className="hq-skin"
      d={`M${-build.shoulder} ${shoulderY} L${build.shoulder} ${shoulderY} L${build.hip} ${hipY} L${-build.hip} ${hipY} Z`}
    />
  );
}

/**
 * The garment.
 *
 * Drawn over the torso as its own silhouette rather than as a fill on it, so
 * lapels, a hood or a shoulder yoke change the *outline* of the person. An
 * outfit that only recolours the torso is invisible in a thumbnail.
 */
function Garment({
  outfit,
  build,
  shoulderY,
  hipY,
}: {
  outfit: Outfit;
  build: Build;
  shoulderY: number;
  hipY: number;
}) {
  const s = build.shoulder;
  const h = build.hip;
  const body = `M${-s} ${shoulderY} L${s} ${shoulderY} L${h} ${hipY} L${-h} ${hipY} Z`;

  switch (outfit) {
    case "blazer":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* Open lapels leave a wedge of shirt: the executive read. */}
          <path
            className="hq-garment-light"
            d={`M-4 ${shoulderY} L4 ${shoulderY} L2 ${hipY} L-2 ${hipY} Z`}
          />
          <path className="hq-garment-dark" d={`M${-s} ${shoulderY} L-3 ${shoulderY + 12} L-6 ${hipY} L${-h} ${hipY} Z`} />
          <path className="hq-garment-dark" d={`M${s} ${shoulderY} L3 ${shoulderY + 12} L6 ${hipY} L${h} ${hipY} Z`} />
        </g>
      );
    case "field-jacket":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* Chest pockets and a raised collar — kit, not tailoring. */}
          <rect className="hq-garment-dark" x={-9} y={shoulderY + 5} width={6} height={5} rx={1} />
          <rect className="hq-garment-dark" x={3} y={shoulderY + 5} width={6} height={5} rx={1} />
          <path className="hq-garment-dark" d={`M-7 ${shoulderY} L7 ${shoulderY} L5 ${shoulderY - 3} L-5 ${shoulderY - 3} Z`} />
        </g>
      );
    case "cardigan":
      return (
        <g>
          <path className="hq-garment" d={body} />
          <path className="hq-garment-light" d={`M-3 ${shoulderY} L3 ${shoulderY} L2 ${hipY} L-2 ${hipY} Z`} />
          {/* Buttons: the softest, most domestic cue in the cast. */}
          {[0, 1, 2].map((i) => (
            <circle key={i} className="hq-garment-dark" cx={0} cy={shoulderY + 7 + i * 5} r={1.2} />
          ))}
        </g>
      );
    case "vest":
      return (
        <g>
          <path className="hq-skin" d={body} />
          <path
            className="hq-garment"
            d={`M${-s + 3} ${shoulderY} L${s - 3} ${shoulderY} L${h - 1} ${hipY} L${-h + 1} ${hipY} Z`}
          />
        </g>
      );
    case "yoke":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* A structural shoulder yoke. Reads as uniform: the security silhouette. */}
          <path
            className="hq-garment-dark"
            d={`M${-s - 1} ${shoulderY - 1} L${s + 1} ${shoulderY - 1} L${s - 2} ${shoulderY + 6} L${-s + 2} ${shoulderY + 6} Z`}
          />
        </g>
      );
    case "hoodie":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* The hood behind the neck is the strongest single silhouette cue
              available to a seated figure. */}
          <path
            className="hq-garment-dark"
            d={`M-8 ${shoulderY + 1} Q0 ${shoulderY - 9} 8 ${shoulderY + 1} Z`}
          />
          <path className="hq-garment-light" d={`M-1 ${shoulderY + 3} L1 ${shoulderY + 3} L1 ${hipY - 4} L-1 ${hipY - 4} Z`} />
        </g>
      );
    case "rolled-shirt":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* Cuffs sit high: sleeves rolled, mid-task. */}
          <rect className="hq-garment-light" x={-s} y={shoulderY + 9} width={4} height={3} />
          <rect className="hq-garment-light" x={s - 4} y={shoulderY + 9} width={4} height={3} />
          <path className="hq-garment-light" d={`M-3 ${shoulderY} L3 ${shoulderY} L0 ${shoulderY + 7} Z`} />
        </g>
      );
    case "utility":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* Belt line across the hips — the coordinator who is never seated. */}
          <rect className="hq-garment-dark" x={-h - 1} y={hipY - 5} width={h * 2 + 2} height={4} rx={1} />
        </g>
      );
    case "long-coat":
      return (
        <g>
          {/* Falls past the hips, so this silhouette is taller than the body. */}
          <path
            className="hq-garment"
            d={`M${-s} ${shoulderY} L${s} ${shoulderY} L${h + 3} ${hipY + 10} L${-h - 3} ${hipY + 10} Z`}
          />
          <path className="hq-garment-light" d={`M-2 ${shoulderY} L2 ${shoulderY} L2 ${hipY + 8} L-2 ${hipY + 8} Z`} />
        </g>
      );
    case "turtleneck":
      return (
        <g>
          <path className="hq-garment" d={body} />
          {/* Collar swallows the neck: the cleanest, quietest silhouette. */}
          <rect className="hq-garment-dark" x={-5} y={shoulderY - 5} width={10} height={6} rx={2.5} />
        </g>
      );
    case "coveralls":
      return (
        <g>
          {/* One piece, belted at the waist, with a bib seam up the centre.
              The waist band is what separates it from a shirt at desk size. */}
          <path className="hq-garment" d={body} />
          <rect className="hq-garment-dark" x={-h - 1} y={hipY - 9} width={h * 2 + 2} height={3} />
          <path
            className="hq-garment-light"
            d={`M-5 ${shoulderY + 2} L5 ${shoulderY + 2} L5 ${hipY - 10} L-5 ${hipY - 10} Z`}
          />
          <rect className="hq-garment-dark" x={-4} y={shoulderY + 4} width={8} height={4} rx={0.5} />
        </g>
      );
    case "parka":
      return (
        <g>
          {/* Bulkier than the body: shoulders sit proud and the hem flares.
              Reads as somebody dressed for a cold room full of machines. */}
          <path
            className="hq-garment"
            d={`M${-s - 2} ${shoulderY} L${s + 2} ${shoulderY} L${h + 2} ${hipY + 3} L${-h - 2} ${hipY + 3} Z`}
          />
          <path className="hq-garment-dark" d={`M-6 ${shoulderY - 4} L6 ${shoulderY - 4} L5 ${shoulderY + 3} L-5 ${shoulderY + 3} Z`} />
          <path className="hq-garment-light" d={`M-1 ${shoulderY + 3} L1 ${shoulderY + 3} L1 ${hipY + 2} L-1 ${hipY + 2} Z`} />
        </g>
      );
    case "wrap-top":
      return (
        <g>
          {/* A diagonal closure. The only asymmetric garment in the cast, which
              is the whole reason it is legible at 64px. */}
          <path className="hq-garment" d={body} />
          <path
            className="hq-garment-dark"
            d={`M${-s} ${shoulderY} L${s - 2} ${shoulderY + 11} L${h} ${hipY} L${-h} ${hipY} Z`}
          />
        </g>
      );
  }
}

/**
 * THE FACE.
 *
 * The single change that turned the cast from abstract figures into people.
 * Before this the rig drew a coloured head shape with hair on it and nothing
 * else, and no amount of clothing detail could rescue that — a blank oval
 * reads as an icon however well dressed it is.
 *
 * WHAT IS DRAWN, AND WHAT IS NOT
 *
 * Eyes, brows, a nose hint, a mouth and a little colour in the cheeks. That is
 * the whole vocabulary. At the size a desk occupies on screen a head is about
 * fifteen pixels across, so anything finer than this is a smudge that costs
 * geometry and returns nothing. The eyes are deliberately oversized: they are
 * the feature that survives smallest, and they are what makes a figure read as
 * facing the reader.
 *
 * EXPRESSION FOLLOWS POSE, NOT STATE
 *
 * A focused brow when someone is leaning into a screen, a closed eye when
 * someone stretches, an open mouth when someone is mid-sentence. All of it is
 * ambient personality — none of it means anything about MEMESCOPE. A frowning
 * character must never be how a reader learns a subsystem is unhealthy; that
 * is what the state chip and the accessible name are for, and they are text.
 */
function Face({ y, pose, egg }: { y: number; pose: Pose; egg?: EggId }) {
  const eyeX = 3.7;
  const eyeY = y + 0.6;
  const closed = pose === "stretching" || egg === "doze";
  const focused = pose === "looking_at_screen" || pose === "seated_reviewing";
  const speaking = pose === "talking_briefly" || pose === "seated_talk";

  return (
    <g className="hq-face" aria-hidden="true">
      {/* Cheeks first, under everything. A trace of warmth is most of what
          separates a cartoon human from a mannequin. */}
      <ellipse className="hq-blush" cx={-7} cy={y + 3.4} rx={2.4} ry={1.5} />
      <ellipse className="hq-blush" cx={7} cy={y + 3.4} rx={2.4} ry={1.5} />

      {closed ? (
        <g className="hq-eye-line">
          <path d={`M${-eyeX - 2} ${eyeY} q2 2 4 0`} />
          <path d={`M${eyeX - 2} ${eyeY} q2 2 4 0`} />
        </g>
      ) : (
        <g>
          <ellipse className="hq-eye" cx={-eyeX} cy={eyeY} rx={1.7} ry={2.1} />
          <ellipse className="hq-eye" cx={eyeX} cy={eyeY} rx={1.7} ry={2.1} />
          {/* One highlight each. The cheapest possible "there is somebody in
              there", and it is the reason these read as alive rather than as
              drilled holes. */}
          <circle className="hq-eye-light" cx={-eyeX + 0.6} cy={eyeY - 0.7} r={0.55} />
          <circle className="hq-eye-light" cx={eyeX + 0.6} cy={eyeY - 0.7} r={0.55} />
        </g>
      )}

      <g className="hq-brow">
        <path
          d={
            focused
              ? `M${-eyeX - 2.4} ${eyeY - 3.2} L${-eyeX + 2.2} ${eyeY - 2.4}`
              : `M${-eyeX - 2.4} ${eyeY - 3.6} L${-eyeX + 2.2} ${eyeY - 3.9}`
          }
        />
        <path
          d={
            focused
              ? `M${eyeX + 2.4} ${eyeY - 3.2} L${eyeX - 2.2} ${eyeY - 2.4}`
              : `M${eyeX + 2.4} ${eyeY - 3.6} L${eyeX - 2.2} ${eyeY - 3.9}`
          }
        />
      </g>

      {/* A nose is a single short stroke. Anything more is a blob. */}
      <path className="hq-nose" d={`M0 ${y + 2.6} l0 2.2`} />

      {speaking ? (
        <ellipse className="hq-mouth-open" cx={0} cy={y + 6.4} rx={1.8} ry={1.4} />
      ) : (
        <path className="hq-mouth" d={`M-2.2 ${y + 6} q2.2 ${focused ? 1.1 : 2} 4.4 0`} />
      )}
    </g>
  );
}

function Head({ shape, y }: { shape: HeadShape; y: number }) {
  switch (shape) {
    case "round":
      return <circle className="hq-skin" cx={0} cy={y} r={HEAD.radius} />;
    case "oval":
      return <ellipse className="hq-skin" cx={0} cy={y} rx={HEAD.radius - 1.5} ry={HEAD.radius + 1} />;
    case "square":
      return (
        <rect
          className="hq-skin"
          x={-HEAD.radius}
          y={y - HEAD.radius}
          width={HEAD.radius * 2}
          height={HEAD.radius * 2}
          rx={3.5}
        />
      );
  }
}

/**
 * Hair.
 *
 * Ten styles that differ in *outline*, not in parting. At this size an
 * interior detail is a smudge; only the shape against the background survives,
 * so each of these changes the head's silhouette.
 */
function Hair({ style, shape, y }: { style: HairStyle; shape: HeadShape; y: number }) {
  const r = shape === "square" ? HEAD.radius : HEAD.radius;
  const top = y - r;

  switch (style) {
    case "cropped":
      return <path className="hq-hair" d={`M${-r} ${y - 1} Q0 ${top - 3} ${r} ${y - 1} L${r} ${y - 4} Q0 ${top - 5} ${-r} ${y - 4} Z`} />;
    case "buzz":
      return <path className="hq-hair" d={`M${-r} ${y - 2} Q0 ${top - 1} ${r} ${y - 2} Z`} />;
    case "bun":
      return (
        <g>
          <path className="hq-hair" d={`M${-r} ${y} Q0 ${top - 4} ${r} ${y} L${r} ${y - 5} Q0 ${top - 6} ${-r} ${y - 5} Z`} />
          <circle className="hq-hair" cx={0} cy={top - 5} r={4.5} />
        </g>
      );
    case "ponytail":
      return (
        <g>
          <path className="hq-hair" d={`M${-r} ${y - 1} Q0 ${top - 3} ${r} ${y - 1} L${r} ${y - 5} Q0 ${top - 5} ${-r} ${y - 5} Z`} />
          <path className="hq-hair" d={`M${r - 2} ${y - 3} Q${r + 7} ${y + 3} ${r + 3} ${y + 11} L${r - 1} ${y + 9} Q${r + 3} ${y + 2} ${r - 4} ${y - 1} Z`} />
        </g>
      );
    case "wavy":
      return <path className="hq-hair" d={`M${-r - 1} ${y + 3} Q${-r} ${top - 4} 0 ${top - 3} Q${r} ${top - 4} ${r + 1} ${y + 3} Q${r - 2} ${y - 2} 0 ${y - 4} Q${-r + 2} ${y - 2} ${-r - 1} ${y + 3} Z`} />;
    case "curly-short":
      return (
        <g>
          {[-6, -2, 2, 6].map((dx, i) => (
            <circle key={i} className="hq-hair" cx={dx} cy={top + (i % 2 === 0 ? 1 : -1)} r={4} />
          ))}
        </g>
      );
    case "long-straight":
      return (
        <g>
          <path className="hq-hair" d={`M${-r - 1} ${y - 2} Q0 ${top - 4} ${r + 1} ${y - 2} L${r + 1} ${y + 12} L${r - 2} ${y + 12} L${r - 2} ${y} L${-r + 2} ${y} L${-r + 2} ${y + 12} L${-r - 1} ${y + 12} Z`} />
        </g>
      );
    case "locs":
      return (
        <g>
          <path className="hq-hair" d={`M${-r} ${y - 2} Q0 ${top - 4} ${r} ${y - 2} Z`} />
          {[-7, -3.5, 0, 3.5, 7].map((dx, i) => (
            <rect key={i} className="hq-hair" x={dx - 1.3} y={y - 3} width={2.6} height={9 + (i % 2) * 3} rx={1.3} />
          ))}
        </g>
      );
    case "tuft":
      return (
        <g>
          <path className="hq-hair" d={`M${-r} ${y - 1} Q0 ${top - 2} ${r} ${y - 1} Z`} />
          {/* One unruly lock. The only asymmetric hair in the cast. */}
          <path className="hq-hair" d={`M2 ${top - 1} Q6 ${top - 8} 10 ${top - 2} Q6 ${top - 3} 3 ${top + 1} Z`} />
        </g>
      );
    case "swept":
      return <path className="hq-hair" d={`M${-r - 1} ${y - 1} Q${-2} ${top - 6} ${r + 2} ${y - 5} L${r} ${y - 1} Q0 ${top - 2} ${-r} ${y + 1} Z`} />;
    case "flat-top":
      // Squared off across the top. The only flat crown in the cast, which is
      // what makes it read at 64px against nine rounded ones.
      return <path className="hq-hair" d={`M${-r} ${y - 1} L${-r} ${top - 4} L${r} ${top - 4} L${r} ${y - 1} L${r} ${y - 4} L${-r} ${y - 4} Z`} />;
    case "shaggy":
      return (
        <g>
          <path className="hq-hair" d={`M${-r - 1} ${y + 1} Q0 ${top - 5} ${r + 1} ${y + 1} Z`} />
          {/* Points falling over the brow. Untidy on purpose. */}
          {[-6, -2, 2, 6].map((dx, i) => (
            <path key={i} className="hq-hair" d={`M${dx - 2.4} ${y - 4} L${dx} ${y + 2 + (i % 2) * 2} L${dx + 2.4} ${y - 4} Z`} />
          ))}
        </g>
      );
    case "braid":
      return (
        <g>
          <path className="hq-hair" d={`M${-r} ${y - 1} Q0 ${top - 3} ${r} ${y - 1} L${r} ${y - 5} Q0 ${top - 5} ${-r} ${y - 5} Z`} />
          {/* A single plait down one side, drawn as stacked segments — the
              read that separates it from the ponytail's smooth sweep. */}
          {[0, 1, 2].map((i) => (
            <ellipse key={i} className="hq-hair" cx={-r - 1} cy={y + 1 + i * 4} rx={2.6} ry={2.4} />
          ))}
        </g>
      );
  }
}

/**
 * Arms.
 *
 * Two per character, and posture is carried almost entirely here. A pair of
 * arms reaching forward reads as typing; one raised reads as holding
 * something. Nothing else in the rig changes between poses, which is what
 * makes the poses cheap enough to animate later.
 */
function Arms({ pose, build, shoulderY }: { pose: Pose; build: Build; shoulderY: number }) {
  const s = build.shoulder;
  const y = shoulderY + 3;

  if (pose === "standing" || pose === "walking_short" || pose === "returning_to_desk") {
    // The same arms whether standing or walking. The swing is a CSS rotation on
    // this group, so a walk costs no extra geometry — which is the only reason
    // walking was affordable at all.
    return (
      <g className="hq-arms">
        <g className="hq-arm hq-arm--left">
          <path className="hq-garment" d={`M${-s} ${y} q-4 8 -2 16 l4 0 q-1 -8 2 -14 Z`} />
          <circle className="hq-hand" cx={-s + 1} cy={y + 17} r={HAND} />
        </g>
        <g className="hq-arm hq-arm--right">
          <path className="hq-garment" d={`M${s} ${y} q4 8 2 16 l-4 0 q1 -8 -2 -14 Z`} />
          <circle className="hq-hand" cx={s - 1} cy={y + 17} r={HAND} />
        </g>
      </g>
    );
  }

  if (pose === "stretching") {
    // Both arms up and back. The one unmistakably human pose in the set, and
    // the reason it is rationed to Byte and to late shifts.
    return (
      <g className="hq-arms">
        <path className="hq-garment" d={`M${-s} ${y} q-7 -6 -5 -15 l4 -1 q0 8 5 13 Z`} />
        <path className="hq-garment" d={`M${s} ${y} q7 -6 5 -15 l-4 -1 q0 8 -5 13 Z`} />
        <circle className="hq-hand" cx={-s - 4} cy={y - 15} r={HAND} />
        <circle className="hq-hand" cx={s + 4} cy={y - 15} r={HAND} />
      </g>
    );
  }

  if (pose === "talking_briefly") {
    // One arm out, palm open; the other stays down. Asymmetry is what makes a
    // gesture read as speech rather than as a shrug.
    return (
      <g className="hq-arms">
        <path className="hq-garment" d={`M${-s} ${y} q-4 7 -1 13 l4 -1 q-2 -6 1 -11 Z`} />
        <circle className="hq-hand" cx={-s + 2} cy={y + 13} r={HAND} />
        <g className="hq-arm hq-arm--gesture">
          <path className="hq-garment" d={`M${s} ${y} q7 -1 11 -6 l3 3 q-5 6 -12 8 Z`} />
          {/* An open hand at the end of the gesture. A sleeve pointing at
              nothing reads as a shrug; a hand reads as speech. */}
          <circle className="hq-hand" cx={s + 13} cy={y - 5} r={HAND + 0.4} />
        </g>
      </g>
    );
  }

  if (pose === "holding_tablet" || pose === "coffee_idle") {
    return (
      <g className="hq-arms">
        {/* One arm crosses the body to hold something at chest height. */}
        <path className="hq-garment" d={`M${-s} ${y} q-3 7 3 11 l5 -3 q-4 -4 -3 -9 Z`} />
        <path className="hq-garment" d={`M${s} ${y} q4 7 1 13 l-4 -1 q2 -6 -2 -11 Z`} />
        <circle className="hq-hand" cx={-s + 6} cy={y + 10} r={HAND} />
        <circle className="hq-hand" cx={s - 2} cy={y + 13} r={HAND} />
      </g>
    );
  }

  if (pose === "seated_reviewing") {
    return (
      <g className="hq-arms">
        {/* Elbow on the desk, chin-ward. Reading, not typing. */}
        <path className="hq-garment" d={`M${-s} ${y} q-4 6 0 11 l5 -2 q-3 -4 -1 -8 Z`} />
        <path className="hq-garment" d={`M${s} ${y} q3 4 -1 7 l-3 4 l-4 -3 q4 -4 3 -7 Z`} />
        <circle className="hq-hand" cx={-s + 4} cy={y + 10} r={HAND} />
        <circle className="hq-hand" cx={s - 6} cy={y + 10} r={HAND} />
      </g>
    );
  }

  if (pose === "seated_lounge") {
    // Hands resting in the lap. The most relaxed silhouette in the rig, and
    // deliberately so: a lounge that reads as work defeats the lounge.
    return (
      <g className="hq-arms">
        <path className="hq-garment" d={`M${-s} ${y} q-3 6 1 10 l5 -1 q-3 -4 -2 -9 Z`} />
        <path className="hq-garment" d={`M${s} ${y} q3 6 -1 10 l-5 -1 q3 -4 2 -9 Z`} />
        <circle className="hq-hand" cx={-3.5} cy={y + 10} r={HAND} />
        <circle className="hq-hand" cx={3.5} cy={y + 10} r={HAND} />
      </g>
    );
  }

  if (pose === "seated_talk") {
    // Seated, one open hand raised mid-point. The meeting pose: enough gesture
    // to read as speech across the table, nothing that reads as alarm.
    return (
      <g className="hq-arms">
        <path className="hq-garment" d={`M${-s} ${y} q-3 6 1 10 l5 -1 q-3 -4 -2 -9 Z`} />
        <circle className="hq-hand" cx={-3.5} cy={y + 10} r={HAND} />
        <g className="hq-arm hq-arm--gesture">
          <path className="hq-garment" d={`M${s} ${y} q7 -2 10 -7 l3 3 q-4 6 -11 8 Z`} />
          <circle className="hq-hand" cx={s + 12} cy={y - 6} r={HAND + 0.3} />
        </g>
      </g>
    );
  }

  if (pose === "tidying") {
    // The support staff's working stance: one arm extended down into the task,
    // the other steadying. Paired with a slight lean from CSS.
    return (
      <g className="hq-arms">
        <path className="hq-garment" d={`M${-s} ${y} q-2 7 2 12 l4 -2 q-2 -5 -1 -10 Z`} />
        <circle className="hq-hand" cx={-s + 3} cy={y + 12} r={HAND} />
        <g className="hq-arm hq-arm--gesture">
          <path className="hq-garment" d={`M${s} ${y} q8 3 10 10 l-4 2 q-3 -6 -9 -8 Z`} />
          <circle className="hq-hand" cx={s + 9} cy={y + 11} r={HAND + 0.3} />
        </g>
      </g>
    );
  }

  // seated_working and looking_at_screen — both hands forward at keyboard
  // height. `looking_at_screen` differs by a lean, which is a CSS rotation on
  // the whole figure rather than a second pair of arms.
  return (
    <g className="hq-arms">
      <path className="hq-garment" d={`M${-s} ${y} q-3 6 2 10 l6 -2 q-4 -4 -3 -7 Z`} />
      <path className="hq-garment" d={`M${s} ${y} q3 6 -2 10 l-6 -2 q4 -4 3 -7 Z`} />
      {/* Hands on the keyboard. Slightly oversized on purpose: at this scale a
          correctly proportioned hand is invisible, and what a reader needs to
          see is that somebody is typing. */}
      <circle className="hq-hand" cx={-s + 5} cy={y + 9} r={HAND} />
      <circle className="hq-hand" cx={s - 5} cy={y + 9} r={HAND} />
    </g>
  );
}

/**
 * The accessory.
 *
 * The most legible identifier at small size, because it breaks the outline in
 * a place nothing else does. Every one of the ten is a different shape in a
 * different position.
 */
function AccessoryPart({
  accessory,
  pose,
  shoulderY,
}: {
  accessory: Accessory;
  pose: Pose;
  shoulderY: number;
}) {
  const headY = shoulderY - 14;

  switch (accessory) {
    case "duster":
      // Maya's cloth and spray bottle, on the hip. Practical, not caricature.
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={-15} y={shoulderY + 14} width={4} height={7} rx={1} />
          <rect className="hq-cloth" x={10} y={shoulderY + 15} width={6} height={7} rx={1} />
        </g>
      );
    case "toolbox":
      // Sam's toolbox, carried at the side.
      return (
        <g className="hq-accessory">
          <rect className="hq-toolbox" x={12} y={shoulderY + 14} width={12} height={8} rx={1.5} />
          <path className="hq-device-stroke" d={`M${15} ${shoulderY + 14} q3 -4 6 0`} />
        </g>
      );
    case "tablet":
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={4} y={shoulderY + 6} width={13} height={10} rx={1.5} transform={`rotate(-14 10 ${shoulderY + 11})`} />
        </g>
      );
    case "headset":
      return (
        <g className="hq-accessory">
          <path className="hq-device-stroke" d={`M-10 ${headY} Q0 ${headY - 12} 10 ${headY}`} />
          <rect className="hq-device" x={-12.5} y={headY - 2} width={4} height={6} rx={1.5} />
          <rect className="hq-device" x={8.5} y={headY - 2} width={4} height={6} rx={1.5} />
          {/* Boom mic: the cue that survives at any size. */}
          <path className="hq-device-stroke" d={`M-10 ${headY + 4} q-3 5 4 6`} />
        </g>
      );
    case "stylus":
      return <rect className="hq-device" x={9} y={shoulderY + 2} width={2} height={11} rx={1} transform={`rotate(28 10 ${shoulderY + 7})`} />;
    case "visor":
      return (
        <rect
          className="hq-visor"
          x={-9.5}
          y={headY - 2}
          width={19}
          height={5}
          rx={2.5}
        />
      );
    case "shield-badge":
      return (
        <path
          className="hq-device"
          d={`M-13 ${shoulderY + 4} l5 -2 l5 2 v4 q0 4 -5 6 q-5 -2 -5 -6 Z`}
        />
      );
    case "clipboard":
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={5} y={shoulderY + 5} width={11} height={14} rx={1} />
          <rect className="hq-device-clip" x={8} y={shoulderY + 3} width={5} height={3} rx={1} />
        </g>
      );
    case "wrist-terminal":
      return <rect className="hq-device" x={pose === "seated_working" ? 6 : 9} y={shoulderY + 11} width={7} height={5} rx={1.5} />;
    case "tool-belt":
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={-13} y={shoulderY + 16} width={5} height={6} rx={1} />
          <rect className="hq-device" x={8} y={shoulderY + 16} width={5} height={6} rx={1} />
        </g>
      );
    case "mug":
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={6} y={shoulderY + 7} width={7} height={8} rx={1.5} />
          <path className="hq-device-stroke" d={`M13 ${shoulderY + 9} q4 2 0 5`} />
        </g>
      );
    case "glasses":
      return (
        <g className="hq-accessory">
          <circle className="hq-device-stroke" cx={-4} cy={headY} r={3.6} fill="none" />
          <circle className="hq-device-stroke" cx={4} cy={headY} r={3.6} fill="none" />
          <path className="hq-device-stroke" d={`M-0.4 ${headY} h0.8`} />
        </g>
      );
    case "pager":
      // Clipped at the hip, screen out. Reads as "can be reached", which is
      // the entire job description.
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={-14} y={shoulderY + 14} width={6} height={8} rx={1} />
          <rect className="hq-device-clip" x={-12.5} y={shoulderY + 16} width={3} height={2} rx={0.5} />
        </g>
      );
    case "checklist":
      return (
        <g className="hq-accessory">
          <rect className="hq-device" x={5} y={shoulderY + 6} width={10} height={13} rx={1} />
          {/* Ticked rows. Three marks, not text — a legible number of them. */}
          {[0, 1, 2].map((i) => (
            <path
              key={i}
              className="hq-device-stroke"
              d={`M7 ${shoulderY + 10 + i * 3.4} l1.4 1.4 l2.6 -2.8`}
              fill="none"
            />
          ))}
        </g>
      );
  }
}

/**
 * A small telescope, for the one person who would bring one to work.
 *
 * Four primitives, drawn only when the easter egg is active. It is not an
 * accessory in the rig's sense — nobody's identity depends on it, and it must
 * not appear in a portrait.
 */
function Telescope({ shoulderY }: { shoulderY: number }) {
  const y = shoulderY - 12;
  return (
    <g className="hq-telescope" aria-hidden="true">
      <path className="hq-device-stroke" d={`M4 ${y + 6} L14 ${y - 4}`} />
      <rect className="hq-device" x={9} y={y - 8} width={11} height={4} rx={2} transform={`rotate(-45 14 ${y - 6})`} />
      <circle className="hq-device" cx={17} cy={y - 9} r={2.4} />
    </g>
  );
}
