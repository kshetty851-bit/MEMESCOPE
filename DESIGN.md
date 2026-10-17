---
name: MEMESCOPE Newspaper
description: A live crypto broadsheet, set in ink-black newsprint, that cites every figure.
colors:
  ink: "#0d0d0b"
  ink-2: "#161613"
  ink-3: "#1f1f1b"
  paper: "#efe8d8"
  paper-2: "#cdc5b3"
  paper-3: "#9c9584"
  rule: "rgb(239 232 216 / 0.14)"
  rule-strong: "rgb(239 232 216 / 0.55)"
  live-lime: "#c6ff3a"
  data-cyan: "#49d8ff"
  alert-orange: "#ff7a35"
typography:
  nameplate:
    fontFamily: "UnifrakturMaguntia, serif"
    fontSize: "clamp(3.2rem, 11vw, 6rem)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "-0.005em"
  display:
    fontFamily: "Big Shoulders, sans-serif"
    fontSize: "clamp(2.4rem, 4.9vw, 4.9rem)"
    fontWeight: 900
    lineHeight: 0.92
    letterSpacing: "-0.012em"
  headline:
    fontFamily: "Big Shoulders, sans-serif"
    fontSize: "clamp(2rem, 3.6vw, 3.1rem)"
    fontWeight: 900
    lineHeight: 0.95
    letterSpacing: "-0.005em"
  title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "clamp(1.1rem, 1.5vw, 1.27rem)"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Big Shoulders, sans-serif"
    fontSize: "1rem"
    fontWeight: 800
    letterSpacing: "0.04em"
  figures:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "0.82em"
    fontWeight: 400
    fontFeature: "tnum"
rounded:
  print: "2px"
  pill: "999px"
spacing:
  gutter: "clamp(16px, 3.2vw, 44px)"
  column: "clamp(20px, 3vw, 40px)"
  section: "34px"
  row: "10px"
components:
  lab-button:
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "6px 12px"
  lab-button-hover:
    backgroundColor: "{colors.live-lime}"
    textColor: "{colors.ink}"
  updates-pill:
    backgroundColor: "{colors.live-lime}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  chip:
    textColor: "{colors.paper-2}"
    rounded: "{rounded.pill}"
    padding: "5px 11px"
  chip-on:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  kind-tag:
    rounded: "{rounded.print}"
    padding: "1px 7px"
  risk-high:
    backgroundColor: "{colors.alert-orange}"
    textColor: "{colors.ink}"
    rounded: "{rounded.print}"
    padding: "2px 7px"
  badge-ours:
    backgroundColor: "{colors.data-cyan}"
    textColor: "{colors.ink}"
    rounded: "{rounded.print}"
    padding: "1px 6px"
---

# Design System: MEMESCOPE Newspaper

Scope: this file governs only the newspaper home page shown after sign-in (route `/home`, `frontend/src/components/newsroom/`, tokens under the `.np` scope in `frontend/src/styles/newspaper.css`). The public landing at `/` and the dashboard labs are a separate, older space-themed world and are not governed by this file.

## Overview

**Creative North Star: "The Night Edition"**

The homepage is a broadsheet printed on black: a blackletter nameplate over a double rule, one lead story at tabloid scale, then sections set in columns divided by hairline rules. It refuses the glowing-neon crypto dashboard of identical cards. Structure comes from rules, columns and type scale, not from boxes or shadows. Density is a newspaper's: many rows, tight leading in headlines, generous measure in reading text.

Colour is ink and paper first. Three accents carry meaning, never decoration: lime says live or up, orange says down or danger, cyan says a link or MEMESCOPE's own data. Every figure is set in mono with tabular numerals and sits next to its source and time.

Motion is print-like and quiet: the nameplate inks in once, sections rise into place once, the ticker drifts slowly and pauses on hover, focus or the pause control. New wire items wait behind an "updates" pill rather than shifting the page. Everything stops under reduced motion.

**Key Characteristics:**
- Ink-black ground with a fixed fractal-noise grain at 8% overlay, plus two faint colour washes (cyan top right, lime left).
- Four families, each with one job: blackletter flag, condensed grotesque heads, serif reading text, mono figures.
- Hairline column rules and 3px double rules instead of cards.
- Accents mean live/up, down/alert, link/ours; nothing else.
- Every number cites its source and time.

## Colors

A near-black newsprint palette with warm off-white type and three semantic accents.

### Primary
- **Live Lime** (live-lime): the live heartbeat dot, up moves, the "60 seconds" top rule, the lead's drop cap, the active tab ink, the updates pill, hover on links and the Lab button, heatmap gains.

### Secondary
- **Alert Orange** (alert-orange): down moves, stale/down status dots, the Security Desk heading, "Developing" tags, high and elevated risk labels, hack icons, heatmap losses.

### Tertiary
- **Data Cyan** (data-cyan): outbound source links, the focus ring, map pins, "Commentary" tags, and the "Our lab" badge and panel that mark MEMESCOPE's own numbers.

### Neutral
- **Ink** (ink): the page ground and the text colour on any filled accent.
- **Ink 2 / Ink 3** (ink-2, ink-3): loading-shimmer bars and the base the heatmap mixes its accent into.
- **Paper** (paper): primary text, headlines, prices, the selected chip fill.
- **Paper 2** (paper-2): secondary text, deks, the masthead rail, unselected chips and tabs.
- **Paper 3** (paper-3): timestamps, captions, fine print, labels in figure lists, bullet dashes.
- **Rule / Rule Strong** (rule, rule-strong): hairline column and row dividers; strong for double rules, the search underline, the Lab button outline and dashed "missing" boxes.

### Named Rules
**The Three Meanings Rule.** Lime is live or up, orange is down or danger, cyan is a link or our own data. An accent that means none of these does not ship.

**The Ink On Accent Rule.** Text on any filled accent (pill, risk label, badge, strong heatmap cell) is ink, never paper.

## Typography

**Nameplate Font:** UnifrakturMaguntia (with serif)
**Display Font:** Big Shoulders 600/800/900 (with sans-serif)
**Body Font:** Source Serif 4 400/600, italic (with Georgia, serif)
**Label/Mono Font:** Geist Mono 400/500 (with ui-monospace)

**Character:** A blackletter flag and condensed uppercase tabloid heads give the page its newspaper voice; a calm serif does the reading; mono is reserved for figures so numbers line up and read as data.

### Hierarchy
- **Nameplate** (400, clamp(3.2rem, 11vw, 6rem), 1): the MEMESCOPE flag in the masthead, and at 2.6rem in the colophon. Nowhere else.
- **Display** (900, clamp(2.4rem, 4.9vw, 4.9rem), 0.92, uppercase, balanced): the lead headline only.
- **Headline** (900, clamp(2rem, 3.6vw, 3.1rem), 0.95, uppercase): section heads. Sub-heads in rails and panels step down to 1.55rem to 1.7rem, same weight and case; major wire items use 800 at clamp(1.5rem, 2.4vw, 2.1rem).
- **Title** (serif 600, clamp(1.1rem, 1.5vw, 1.27rem), 1.3): ordinary wire headlines.
- **Body** (serif 400, 1.0625rem, 1.55; 1rem under 640px): reading text, deks capped at 60ch to 70ch.
- **Label** (800, 0.8rem to 1rem, 0.04em to 0.06em, uppercase): tabs, tags, risk labels, the Lab button, figure-list terms (700).
- **Figures** (mono, 0.82em of context, tabular): every price, percentage, time, count and countdown.

### Named Rules
**The Figures Are Mono Rule.** A number that is data (price, change, time, count) is set in the mono face with tabular numerals; prose numbers are not.

**The One Flag Rule.** Blackletter is the nameplate. It never sets a heading, label or body text.

## Layout

A centred page capped at 1480px with a fluid gutter (spacing.gutter). The front page is a two-column grid: the lead takes the wide column (1fr) and the "Crypto in 60 seconds" briefing the narrow one (minmax(300px, 0.42fr)), divided by a hairline. Later sections repeat that newspaper split: wire plus a sticky right rail, map plus panel, memes beside on-chain, hacks beside a security wire. Columns are separated by a 1px rule with column padding (spacing.column) on the inner side, never by gaps alone.

Sections stack with 34px vertical padding and a hairline under each. Lists are rows divided by hairlines at roughly 9px to 15px padding; dense tables (movers, memes, drains, events) use fixed-width leading columns for times and symbols so rows align.

At 1024px every split collapses to one column and vertical rules turn into top rules. At 640px the masthead switches to a short date, tables drop secondary columns, and wire times move above headlines.

**The Rules Not Boxes Rule.** Sections and columns are divided by hairlines and double rules. The market pulse grid is the one bordered block, because it is a table of figures.

## Elevation & Depth

Flat. Depth comes from the grain layer, the two faint radial washes in the ground, and tonal steps (ink to ink-3), not from shadows. The only resting shadow-like effect is the live dot's single expanding lime ring when data refreshes. Hover lifts are limited to the heatmap cells (2px rise with slight brightening) and the star control (scale 1.12).

**The Printed Flat Rule.** Nothing on the page casts a shadow at rest. Emphasis is a heavier rule, a larger head or an accent fill.

## Shapes

Print corners: tags, risk labels, badges, heat cells and the missing-data box use a barely-there 2px radius (rounded.print). Interactive pills (the Lab button, filter chips, the updates pill) are fully rounded (rounded.pill). Status dots, map pins and timeline nodes are circles. Rules are 1px hairlines, 3px double rules for the masthead and colophon, a 4px solid lime rule above the briefing head, and a 1px dashed strong rule for "not connected yet" states. Icons are one stroke family: 20px grid, 1.6px stroke, round caps and joins, drawn in currentColor.

## Components

### Buttons
- **Lab button:** label type, 1px strong-rule outline, pill shape, 6px 12px. Hover fills lime with ink text.
- **Updates pill:** lime fill, ink text, label type, pill shape, sticky at the top of the wire; appears only when new items are waiting.
- **Link button:** unstyled text in cyan at 0.92rem, hover lime; used for "Follow the story" and "more" expanders.
- **Focus:** every control gets a 2px cyan outline at 3px offset.

### Chips
- **Style:** transparent, paper-2 text, 1px rule border, pill, 5px 11px at 0.86rem.
- **State:** hover strengthens the border and text to paper; selected fills paper with ink text.

### Tags
- **Kind tag:** label type at 0.8rem, outlined in currentColor, 2px radius. Confirmed is lime, single report paper-2, developing orange, commentary cyan, new is lime filled.
- **Risk label:** high is orange filled, elevated orange outlined, watch strong-rule outlined.
- **Our lab badge:** cyan fill, ink text; heads a cyan-washed panel with a cyan top rule that holds MEMESCOPE's own figures.

### Tabs
- Label-type tabs on a hairline; the active one is paper with a 3px lime ink bar that slides between tabs. Under 640px the bar is replaced by a lime underline on the active tab.

### Inputs / Fields
- **Search:** no box; a strong-rule underline with an inline search icon. Focus turns the underline lime.

### Navigation
- **Masthead rail:** date, issue number, live status and the Lab button on one line above a hairline, paper-2 at 0.86rem; the live dot is lime and turns orange when the edition is stale or the connection is lost.
- **Ticker:** a 40px strip under the masthead, symbols in label type, prices and changes in figures, cells divided by hairlines, 110s loop, with a pause/play control at its left edge.

### Lead Story (signature)
Uppercase display headline with a 4px lime underline on hover, publisher byline and kind tag, a 21:7 image shown grayscale with raised contrast that warms toward colour on hover, a dek opened by a lime drop cap, a cyan "Read at" source link, and a fold-out timeline of reports with the newest node in lime.

### Wire Row
A 52px time column in mono, then a serif headline with a paper-2 dek. Major stories switch the headline to uppercase condensed. Hover shows a faint paper wash fading to the right.

### Not Connected Yet
An italic paper-2 line in a dashed strong-rule box naming the section and why no free source exists. Used instead of placeholder data.

## Do's and Don'ts

### Do:
- **Do** divide columns and sections with 1px hairlines (rule) and close the masthead and colophon with a 3px double rule (rule-strong).
- **Do** set every price, change, time and count in the mono face with tabular numerals, and show its source and time nearby.
- **Do** keep the accents to their meanings: lime live/up, orange down/alert, cyan link/ours.
- **Do** put ink text on filled accents.
- **Do** mark MEMESCOPE's own numbers with the cyan "Our lab" badge and panel.
- **Do** hold new items behind the updates pill; never shift content the reader is on.
- **Do** stop every animation under prefers-reduced-motion and give every control the cyan focus ring.

### Don't:
- **Don't** build sections from stacked identical cards with shadows; the thesis refuses the glowing-neon crypto dashboard.
- **Don't** use blackletter anywhere but the nameplate.
- **Don't** add shadows at rest or glow effects to text or panels.
- **Don't** use an accent colour decoratively or for a fourth meaning.
- **Don't** fill a section with placeholder or invented figures; show the dashed "not connected yet" state.
- **Don't** add text glyphs as icons; use the 1.6px stroke icon family.
