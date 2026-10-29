---
name: MEMESCOPE Newspaper
description: A live crypto broadsheet, printed as a vintage morning paper, that cites every figure.
colors:
  # Morning edition (2026-10-29). CSS token names are historical: --np-ink* hold the paper,
  # --np-paper* hold the ink, --np-lime/-orange/-cyan hold green, vermilion and prussian blue.
  newsprint: "#e9e3d3"
  newsprint-2: "#ddd5c1"
  newsprint-3: "#cfc6ae"
  press-ink: "#1c1a15"
  press-ink-2: "#463f33"
  press-ink-3: "#6b6352"
  rule: "rgb(28 26 21 / 0.2)"
  rule-strong: "rgb(28 26 21 / 0.72)"
  green-ink: "#2f6a3a"
  prussian-blue: "#1f4a7a"
  vermilion: "#b3361b"
typography:
  nameplate:
    fontFamily: "UnifrakturMaguntia, serif"
    fontSize: "clamp(3.2rem, 11vw, 6rem)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "-0.005em"
  display:
    fontFamily: "Bodoni Moda, serif"
    fontSize: "clamp(2.2rem, 4.1vw, 4rem)"
    fontWeight: 900
    lineHeight: 0.92
    letterSpacing: "-0.012em"
  headline:
    fontFamily: "Bodoni Moda, serif"
    fontSize: "clamp(2rem, 3.6vw, 3.1rem)"
    fontWeight: 900
    lineHeight: 0.95
    letterSpacing: "-0.005em"
  title:
    fontFamily: "Old Standard TT, Georgia, serif"
    fontSize: "clamp(1.1rem, 1.5vw, 1.27rem)"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Old Standard TT, Georgia, serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "News Cycle, sans-serif"
    fontSize: "1rem"
    fontWeight: 700
    letterSpacing: "0.04em"
  figures:
    fontFamily: "Courier Prime, ui-monospace, monospace"
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
    textColor: "{colors.press-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "6px 12px"
  lab-button-hover:
    backgroundColor: "{colors.green-ink}"
    textColor: "{colors.newsprint}"
  updates-pill:
    backgroundColor: "{colors.green-ink}"
    textColor: "{colors.newsprint}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  chip:
    textColor: "{colors.press-ink-2}"
    rounded: "{rounded.pill}"
    padding: "5px 11px"
  chip-on:
    backgroundColor: "{colors.press-ink}"
    textColor: "{colors.newsprint}"
  kind-tag:
    rounded: "{rounded.print}"
    padding: "1px 7px"
  risk-high:
    backgroundColor: "{colors.vermilion}"
    textColor: "{colors.newsprint}"
    rounded: "{rounded.print}"
    padding: "2px 7px"
  badge-ours:
    backgroundColor: "{colors.prussian-blue}"
    textColor: "{colors.newsprint}"
    rounded: "{rounded.print}"
    padding: "1px 6px"
---

# Design System: MEMESCOPE Newspaper

Scope: this file governs only the newspaper home page shown after sign-in (route `/home`, `frontend/src/components/newsroom/`, tokens under the `.np` scope in `frontend/src/styles/newspaper.css`). The public landing at `/` and the dashboard labs are a separate, older space-themed world and are not governed by this file.

## Overview

**Creative North Star: "The Morning Edition"** (Karthik, 2026-10-29: "white background like a newspaper, stylish font and animations"; chose vintage newsprint, lively motion)

The homepage is a vintage broadsheet on aged newsprint: a blackletter nameplate over a double rule, Didone heads pressed with a hair of letterpress spread, a news roman for reading and typewriter figures. It refuses the glowing-neon crypto dashboard of identical cards. Structure comes from rules, columns and type scale, not from boxes or shadows.

Colour is paper and press ink first. Three inks carry meaning, never decoration: green says live or up, vermilion says down or danger, prussian blue says a link or MEMESCOPE's own data. Every figure is set in typewriter mono with tabular numerals and sits next to its source and time. Photographs print as sepia halftone and develop to colour on hover.

Motion is one authored moment, the edition coming off the press: the flag stamps letter by letter, the double rule rolls out from the centre, the front page unfolds, the lead head prints word by word and "Crypto in 60 seconds" is typed with a caret. After that, section heads are inked by a roller as they scroll in, changed prices are re-inked, links get a pen-stroke underline and wire rows nudge on hover. New wire items still wait behind the "updates" pill. Everything stops under reduced motion. The AI-anchor TV is a dark set standing on the paper and keeps the night inks inside its own scope.

**Key Characteristics:**
- Newsprint ground (#e9e3d3) with multiplied fibre grain, a tan edge vignette and a fold crease below the first viewport.
- Five faces, each with one job: blackletter flag and lead drop cap, Didone heads, News Gothic labels, news-roman reading text, typewriter figures.
- Hairline column rules and double rules instead of cards; heads carry an SVG letterpress filter (#np-press).
- Inks mean live/up, down/alert, link/ours; nothing else.
- Every number cites its source and time.

## Colors

Aged newsprint and press ink, with three semantic inks.

- **Green ink** (#2f6a3a, token --np-lime): live dot, up moves, brief sub-heads, the active tab bar, the updates pill, heatmap gains.
- **Vermilion** (#b3361b, --np-orange): down moves, stale status, Security Desk head, "Developing", risk labels, heatmap losses.
- **Prussian blue** (#1f4a7a, --np-cyan): links and link hover, focus ring, map pins, "Commentary", the "Our lab" badge and panel.
- **Newsprint 1–3** (--np-ink, -2, -3): the ground, shimmer bars, the heatmap mix base, the stand-in figure.
- **Press ink 1–3** (--np-paper, -2, -3): headlines and prices, secondary text and deks, timestamps and fine print.
- **Rule / Rule strong**: hairlines; strong for double rules and dashed "missing" boxes.

### Named Rules
**The Three Meanings Rule.** Green is live or up, vermilion is down or danger, prussian blue is a link or our own data. An accent that means none of these does not ship.

**The Paper On Ink Rule.** Text on any filled ink (pill, risk label, badge, strong heatmap cell) is newsprint-coloured.

## Typography

**Nameplate Font:** UnifrakturMaguntia (flag, colophon flag, lead drop cap)
**Display Font:** Bodoni Moda 600/800/900 (heads, uppercase)
**Label Font:** News Cycle 400/700 (tags, tabs, ticker symbols, figure-list terms)
**Body Font:** Old Standard TT 400/700, italic
**Figures Font:** Courier Prime 400/700, tabular

**Character:** an old front page: blackletter flag, hairline-contrast Didone heads, a press-room gothic for labels, a 19th-century news roman for reading, typewriter figures.

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

**The One Flag Rule.** Blackletter is the nameplate (and the lead's drop cap). It never sets a heading, label or body text.

## Layout

A centred page capped at 1480px with a fluid gutter (spacing.gutter). The front page is a two-column grid: the lead takes the wide column (1fr) and the "Crypto in 60 seconds" briefing the narrow one (minmax(300px, 0.42fr)), divided by a hairline. Later sections repeat that newspaper split: wire plus a sticky right rail, map plus panel, memes beside on-chain, hacks beside a security wire. Columns are separated by a 1px rule with column padding (spacing.column) on the inner side, never by gaps alone.

Sections stack with 34px vertical padding and a hairline under each. Lists are rows divided by hairlines at roughly 9px to 15px padding; dense tables (movers, memes, drains, events) use fixed-width leading columns for times and symbols so rows align.

At 1024px every split collapses to one column and vertical rules turn into top rules. At 640px the masthead switches to a short date, tables drop secondary columns, and wire times move above headlines.

**The Rules Not Boxes Rule.** Sections and columns are divided by hairlines and double rules. The market pulse grid is the one bordered block, because it is a table of figures.

## Elevation & Depth

Flat. Depth comes from the grain layer, the paper vignette and fold crease, and tonal steps (ink to ink-3), not from shadows. The only resting shadow-like effect is the live dot's single expanding green ring when data refreshes. Hover lifts are limited to the heatmap cells (2px rise with a slight tilt) and the star control (scale 1.12).

**The Printed Flat Rule.** Nothing on the page casts a shadow at rest. Emphasis is a heavier rule, a larger head or an accent fill.

## Shapes

Print corners: tags, risk labels, badges, heat cells and the missing-data box use a barely-there 2px radius (rounded.print). Interactive pills (the Lab button, filter chips, the updates pill) are fully rounded (rounded.pill). Status dots, map pins and timeline nodes are circles. Rules are 1px hairlines, 3px double rules for the masthead and colophon, a 4px solid green rule above the briefing head, and a 1px dashed strong rule for "not connected yet" states. Icons are one stroke family: 20px grid, 1.6px stroke, round caps and joins, drawn in currentColor.

## Components

### Buttons
- **Lab button:** label type, 1px strong-rule outline, pill shape, 6px 12px. Hover fills press ink with newsprint text.
- **Updates pill:** green-ink fill, newsprint text, label type, pill shape, sticky at the top of the wire; appears only when new items are waiting.
- **Link button:** unstyled text in prussian blue at 0.92rem; used for "Follow the story" and "more" expanders.
- **Focus:** every control gets a 2px prussian blue outline at 3px offset.

### Chips
- **Style:** transparent, paper-2 text, 1px rule border, pill, 5px 11px at 0.86rem.
- **State:** hover strengthens the border and text to paper; selected fills paper with ink text.

### Tags
- **Kind tag:** label type at 0.8rem, outlined in currentColor, 2px radius. Confirmed is green, single report press-ink-2, developing vermilion, commentary prussian blue, new is green filled.
- **Risk label:** high is vermilion filled, elevated vermilion outlined, watch strong-rule outlined.
- **Our lab badge:** prussian blue fill, ink text; heads a prussian blue-washed panel with a prussian blue top rule that holds MEMESCOPE's own figures.

### Tabs
- Label-type tabs on a hairline; the active one is press ink with a 3px green bar that slides between tabs. Under 640px the bar is replaced by a green underline on the active tab.

### Inputs / Fields
- **Search:** no box; a strong-rule underline with an inline search icon. Focus turns the underline green.

### Navigation
- **Masthead rail:** date, issue number, live status and the Lab button on one line above a hairline, paper-2 at 0.86rem; the live dot is green and turns vermilion when the edition is stale or the connection is lost.
- **Ticker:** a 40px strip under the masthead, symbols in label type, prices and changes in figures, cells divided by hairlines, 110s loop, with a pause/play control at its left edge.

### Lead Story (signature)
Uppercase display headline with a 4px green underline on hover, publisher byline and kind tag, a 21:7 image shown grayscale with raised contrast that warms toward colour on hover, a dek opened by a green drop cap, a prussian blue "Read at" source link, and a fold-out timeline of reports with the newest node in green.

### Wire Row
A 52px time column in mono, then a serif headline with a paper-2 dek. Major stories switch the headline to uppercase Didone. Hover nudges the row 4px right under a faint ink wash and draws a pen-stroke underline.

### Not Connected Yet
An italic paper-2 line in a dashed strong-rule box naming the section and why no free source exists. Used instead of placeholder data.

## Do's and Don'ts

### Do:
- **Do** divide columns and sections with 1px hairlines (rule) and close the masthead and colophon with a 3px double rule (rule-strong).
- **Do** set every price, change, time and count in the mono face with tabular numerals, and show its source and time nearby.
- **Do** keep the accents to their meanings: green live/up, vermilion down/alert, prussian blue link/ours.
- **Do** put newsprint-coloured text on filled inks.
- **Do** mark MEMESCOPE's own numbers with the prussian blue "Our lab" badge and panel.
- **Do** hold new items behind the updates pill; never shift content the reader is on.
- **Do** stop every animation under prefers-reduced-motion and give every control the prussian blue focus ring.

### Don't:
- **Don't** build sections from stacked identical cards with shadows; the thesis refuses the glowing-neon crypto dashboard.
- **Don't** use blackletter anywhere but the nameplate and the lead drop cap.
- **Don't** add shadows at rest or glow effects to text or panels.
- **Don't** use an accent colour decoratively or for a fourth meaning.
- **Don't** fill a section with placeholder or invented figures; show the dashed "not connected yet" state.
- **Don't** add text glyphs as icons; use the 1.6px stroke icon family.
