---
name: 4-Track
description: Turn one sung phrase into a four-part a cappella arrangement, on a home 4-track deck rendered in 8-bit.
colors:
  ink-ground: "#15131F"
  deck-panel: "#1D1A2B"
  grid-line: "#2C2840"
  counter-well: "#0C0B13"
  paper-cream: "#F4EFE6"
  cream-edge: "#C9C1B3"
  dusk-muted: "#A8A3BC"
  cream-wash: "rgba(244,239,230,0.06)"
  track-coral: "#FF6B5B"
  track-amber: "#FFBE3D"
  amber-edge: "#C98E1C"
  track-mint: "#4FDBA0"
  track-blue: "#6AA8FF"
  pitch-on: "#9CF06A"
  pitch-near: "#FFE45C"
  pitch-off: "#FF4D4D"
typography:
  display:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "28px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.03em"
  headline:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "30px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.01em"
  counter:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "30px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.06em"
    fontFeature: "tnum"
  option:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "26px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.04em"
  title:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "23px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.01em"
  label:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "22px"
    fontWeight: 400
    letterSpacing: "0.04em"
  control:
    fontFamily: "Jersey 15, ui-monospace, monospace"
    fontSize: "20px"
    fontWeight: 400
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.35
  meta:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.3
  tab:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 600
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "10px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
components:
  button-primary:
    backgroundColor: "{colors.paper-cream}"
    textColor: "{colors.ink-ground}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    height: "52px"
  button-play:
    backgroundColor: "{colors.paper-cream}"
    textColor: "{colors.ink-ground}"
    rounded: "{rounded.xs}"
    size: "46px x 42px"
  button-play-active:
    backgroundColor: "{colors.track-amber}"
    textColor: "{colors.ink-ground}"
  chip-ms:
    textColor: "{colors.ink-ground}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    size: "38px"
  chip-ms-active:
    backgroundColor: "{colors.ink-ground}"
    textColor: "{colors.paper-cream}"
  track-row:
    textColor: "{colors.ink-ground}"
    typography: "{typography.title}"
    rounded: "{rounded.lg}"
    padding: "8px 10px 8px 16px"
    height: "58px"
  track-row-off:
    backgroundColor: "{colors.deck-panel}"
    textColor: "{colors.dusk-muted}"
  track-empty:
    textColor: "{colors.track-blue}"
    rounded: "{rounded.lg}"
    padding: "0 16px"
    height: "58px"
  tape-counter:
    backgroundColor: "{colors.counter-well}"
    textColor: "{colors.track-amber}"
    typography: "{typography.counter}"
    rounded: "{rounded.xs}"
    padding: "3px 10px 1px"
  mix-card:
    backgroundColor: "{colors.deck-panel}"
    rounded: "{rounded.sm}"
    height: "176px"
  toast:
    backgroundColor: "{colors.paper-cream}"
    textColor: "{colors.ink-ground}"
    rounded: "{rounded.xs}"
    padding: "9px 12px"
---

# Design System: 4-Track

## Overview

**Creative North Star: "The Bedroom Portastudio"**

4-Track looks like a home four-track cassette recorder on a desk at night: a dark deck, a glowing tape counter, and four coloured channels, one per voice. The 8-bit layer (Jersey 15 pixel type, square note blocks) makes it playful without turning it into a game. Everything that isn't a voice stays dark and quiet, so colour always means a part someone sings.

Density is calm. One layered mix sits on top, the four voices sit below as solid colour blocks, and there is one obvious next action. Labels that restate what the layout already shows are left out. Controls are flat and soft. Only the main action (and the play key) is a raised cream key that presses down.

**Key Characteristics:**
- Dark ink-blue deck; colour is reserved for the four voices.
- Each voice owns one colour everywhere: its row, its notes in the mix, its lane in future screens.
- Jersey 15 for every pixel voice; the system sans for small reading text.
- Flat, soft controls; one raised cream key for the primary action.
- Square 8-bit note blocks with a darker bottom bevel.

## Colors

A dark, slightly violet deck with four saturated voice colours and one warm cream for actions.

### Primary
- **Track Coral** (track-coral): track 1, the melody. Its row, its notes in the mix, its contour anywhere else.
- **Track Amber** (track-amber): track 2. Also the tape counter digits, the active play key, the current tab icon, and text selection. Amber is the one voice colour allowed to double as the "live" signal.
- **Track Mint** (track-mint): track 3.
- **Track Blue** (track-blue): track 4. Also the dashed outline and text of an empty "Add …" slot.

### Secondary
- **Pitch Lime** (pitch-on): the sung pitch line and cents readout when within tolerance, and the "Headphones on" light.
- **Pitch Lemon** (pitch-near): sung pitch within twice the tolerance.
- **Pitch Red** (pitch-off): sung pitch beyond twice the tolerance.

### Neutral
- **Ink Ground** (ink-ground): the screen background and the text colour on every colour block.
- **Deck Panel** (deck-panel): raised surfaces (the mix card) and any voice row that is muted or not soloed.
- **Grid Line** (grid-line): the bar line in the piano roll.
- **Counter Well** (counter-well): the recessed window behind the tape counter.
- **Paper Cream** (paper-cream): primary text on dark, the primary button, the play key, and toasts.
- **Cream Edge** (cream-edge) and **Amber Edge** (amber-edge): the 4px bottom edge of raised keys in their resting and active colours.
- **Dusk Muted** (dusk-muted): secondary text on dark (song details, tab labels, muted rows). 7.5:1 on the ground.
- **Cream Wash** (cream-wash): the faint fill for chips and dividers on a dark (off) row.

### Named Rules
**The Four Voices Rule.** Coral, amber, mint, and blue mean tracks 1–4 and nothing else. Never use a track colour for decoration, a status, or a generic accent; if it's coloured, someone sings it.

**The Accuracy Exception.** Pitch Lime, Lemon, and Red exist only to grade a singer's pitch, on the Practice screen and in its results. They never mark a voice, and voices never use them. On those screens the target notes stay neutral (cream outlines), so a voice colour and an accuracy colour never sit side by side. Every accuracy colour is paired with words ("On pitch", "Close · flat").

**The Ink-On-Colour Rule.** Text on a colour block is always ink. Secondary text on colour uses ink at 84% opacity (5.2:1 on coral, the weakest pair); never lower.

## Typography

**Display Font:** Jersey 15 (with ui-monospace fallback)
**Body Font:** the system sans (-apple-system / SF Pro Text)

**Character:** Jersey 15 is a soft-cornered pixel face: 8-bit without being loopy or jagged. The system sans does the small, readable work underneath it.

### Hierarchy
- **Headline** (Jersey 15, 30px, line-height 1): the song title.
- **Counter** (Jersey 15, 30px, tabular figures, 0.06em): the tape counter, bar.beat (`01.3`).
- **Display** (Jersey 15, 28px, 0.03em): the 4-TRACK wordmark beside the four stripes.
- **Option** (Jersey 15, 26px, 0.04em, uppercase): the current harmony option name (PARALLEL 3RDS).
- **Title** (Jersey 15, 23px): voice names in track rows (Melody, Alto).
- **Label** (Jersey 15, 22px, 0.04em, uppercase): the primary button.
- **Control** (Jersey 15, 20px): M / S chips.
- **Body** (system, 15px, 1.35): default reading text.
- **Meta** (system 500, 13px): singer names, song details, option descriptions.
- **Tab** (system 600, 11px): tab bar labels.

### Named Rules
**The One Pixel Face Rule.** Every pixel-style word is Jersey 15. No second pixel font, ever; mixing pixel faces is what made earlier versions look busy.

**The Readable Floor Rule.** Anything under 16px is set in the system sans, never the pixel face. Nothing functional goes below 11px.

## Layout

A single phone column (390 × 844 reference) with 20px side margins. Top to bottom: status bar, wordmark row (44px), song row (title + counter + play), the mix card (176px), the track rows (8px apart), the primary button pinned 100px above the bottom, and the tab bar (83px).

Spacing steps are 4, 8, 12, 16, and 20px. Rows group tightly (8px); sections separate at 16px. There is no multi-column layout; on narrow phones the column simply goes full-bleed.

## Elevation & Depth

Flat by default. Depth comes from tone (ink ground → deck panel → counter well), not shadows. The only "shadow" is the 4px inset bottom edge on raised keys (cream edge at rest, amber edge when active), which reads as a physical key and drops 2px when pressed.

**The Flat Deck Rule.** Panels and rows never get drop shadows. Only pressable keys get the bottom edge.

## Shapes

Gently rounded, never pill-shaped. Small fixtures use 4px (counter, play key, toast), the mix card and primary button 6px, chips and arrow buttons 8px, and voice rows 10px. Note blocks in the piano roll are square-cornered, which keeps them 8-bit. Empty slots use a 2px dashed outline in the slot's own track colour.

## Components

### Buttons
- **Primary** (button-primary): a full-width cream raised key, 52px tall, Jersey 15 label in ink. Its text names the result ("KEEP 3RDS FOR MAYA") and updates with the selection. Presses down 2px.
- **Play** (button-play): a small cream raised key with a pixel triangle; turns amber with an amber edge while playing.
- **Arrows** (option picker): no fill at rest; a 10% ink wash on hover. 44px tall touch targets.
- **Focus:** a 2px paper-cream outline, offset 2px, on every button.

### Chips (M / S)
- **Style:** 38px soft squares, 8px corners, filled with 10% ink over the row colour (18% on hover). Jersey 15 letters.
- **Pressed:** solid ink with cream letters. On a muted (dark) row, chips sit on cream-wash and the pressed chip inverts to cream with ink letters.

### Track rows (signature)
- **Shape:** 10px corners, 58px minimum height, the whole row in the track's colour.
- **Content:** voice name (Title) over singer name (Meta, ink at 84%), then the M / S chips. Nothing else: no contour strips, number columns, or borders.
- **Off state:** when muted, or when another track is soloed, the row turns deck-panel with dusk-muted text, and the mix card dims that voice's notes to 12% opacity.
- **Picker variant:** the row being arranged expands with a hairline divider (12% ink), ‹ › arrows, the Option name, a Meta description, and square dots for position (current dot solid ink).
- **Empty slot:** a dashed track-blue outline with "Add bass / for Sam" and a pixel plus.

### Mix card
Deck-panel card, 176px tall, holding every voice layered in one piano roll: square note blocks in each track's colour with a 2px darker bottom bevel, faint beat lines, one grid-line bar line, and a cream playhead. No labels or axis text.

### Tape counter
Amber Jersey 15 digits in a recessed counter-well window, bar.beat format, tabular figures so it doesn't jitter while playing.

### Navigation
A borderless tab bar on the ink ground: pixel-drawn SVG icons over system-sans labels in dusk-muted. The current tab turns its label cream and its icon amber.

## Do's and Don'ts

### Do:
- **Do** give every voice exactly one track colour and reuse it everywhere that voice appears.
- **Do** set every pixel-style word in Jersey 15, and everything under 16px in the system sans.
- **Do** keep one cream raised key per screen for the main action, and name the result in its label.
- **Do** dim, rather than hide, voices that are muted or not soloed, so the arranger keeps the context.
- **Do** draw icons as pixel SVGs in one stroke weight.

### Don't:
- **Don't** use a track colour for anything that isn't a voice, or an accuracy colour for anything that isn't pitch grading.
- **Don't** add a second pixel font, or set pixel type below 16px.
- **Don't** add borders, drop shadows, or labels that restate what the layout already shows.
- **Don't** repeat the mix inside each track row; the mix card is the only piano roll on the arranging screen.
- **Don't** put secondary text on a colour block below 84% ink.
