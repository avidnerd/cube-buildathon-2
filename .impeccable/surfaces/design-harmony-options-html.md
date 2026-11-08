---
version: 1
slug: "design-harmony-options-html"
primary_target: "design/harmony-options.html"
related_targets: []
---

# Harmony Options (arranger) — 4-Track

Scope: the arranger's Harmony Options screen, iPhone-first mobile web. Mode: Operate.
Audience and task: an a cappella arranger choosing a harmony line for one member, hearing it against the melody and the parts already chosen.
Constraints: one note model drives every view; one piano roll component; diatonic options; ranges per member.
Chosen structure (refined 2026-11-08: more colour, less clutter): user-pinned hybrid of the dealt "Transport Deck" (layered mix card) and "Four Lanes" (one lane per voice with mute/solo).
Unresolved: real singer names and songs; logo beyond the stripe wordmark.

## Direction contract

THESIS: The screen is a 4-track tape: one layered MIX reel on top, four isolatable track lanes below. It refuses the category default of one roll plus a list of options.
OWN-WORLD: Deep ink-blue deck (#15131F ground, #1D1A2B panels); each voice is a solid colour block: coral #FF6B5B, amber #FFBE3D, mint #4FDBA0, blue #6AA8FF; notes as square 8-bit blocks; Jersey 15 for every pixel voice (logo, title, counter, track names, option name, buttons), system sans for small reading text; cream raised key is the one primary action.
STORY: The arranger sees every part layered, isolates any voice with M/S, flips the alto's options in place, and keeps one.
FIRST VIEWPORT: Wordmark row; Jersey title + amber tape counter + cream play key; MIX card (all tracks layered, 176px, no labels); colour-block track rows (melody, alto with ‹ › picker and dots, tenor, dashed empty bass) with soft M/S chips; cream "KEEP … FOR MAYA" button; tab bar.
FORM: user-pinned structure combining dealt candidates 5 and 2 of the ordered list; seed: none (unavailable)
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
