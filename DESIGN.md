---
name: Painel do Servidor
description: Console doméstico escuro onde brincadeira e produção moram na mesma máquina e nunca se confundem.
colors:
  app: "#1a1b1e"
  side: "#1f2023"
  card: "#25262a"
  ctrl: "#2c2d33"
  line: "#35363d"
  line-soft: "#2b2c32"
  fg: "#e6e7ea"
  dim: "#989aa2"
  dimmer: "#6e707a"
  blue: "#2f7fef"
  blue-hi: "#4b93f5"
  blue-dim: "#1b4f94"
  green: "#3dab62"
  green-dim: "#1f5c36"
  red: "#e5484d"
  red-dim: "#7a2b2e"
  amber: "#e0a23c"
  log-bg: "#131417"
  log-ink: "#c9ccd3"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "normal"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  badge:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.02em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "normal"
rounded:
  pill: "999px"
  md: "8px"
  sm: "6px"
  mark: "5px"
  hairline: "3px"
spacing:
  tight: "4px"
  inner: "7px"
  gap: "9px"
  gap-lg: "13px"
  card: "16px"
  gutter: "24px"
components:
  button-neutral:
    backgroundColor: "{colors.ctrl}"
    textColor: "{colors.fg}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-neutral-hover:
    backgroundColor: "#34353c"
    textColor: "{colors.fg}"
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "#ffffff"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-primary-hover:
    backgroundColor: "{colors.blue-hi}"
    textColor: "#ffffff"
  button-go:
    backgroundColor: "{colors.green}"
    textColor: "#06230f"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-go-hover:
    backgroundColor: "#49c070"
    textColor: "#06230f"
  button-stop:
    backgroundColor: "transparent"
    textColor: "{colors.red}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-stop-hover:
    backgroundColor: "rgba(229,72,77,.12)"
    textColor: "{colors.red}"
  button-small:
    backgroundColor: "{colors.ctrl}"
    textColor: "{colors.fg}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
  input-text:
    backgroundColor: "{colors.ctrl}"
    textColor: "{colors.fg}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "7px 10px"
    width: "100%"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "16px"
  stat:
    backgroundColor: "{colors.card}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "14px 16px"
  action-row:
    backgroundColor: "{colors.card}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "12px 14px"
  tab-primary:
    backgroundColor: "transparent"
    textColor: "{colors.dim}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  tab-primary-active:
    backgroundColor: "{colors.blue}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  subtab:
    backgroundColor: "transparent"
    textColor: "{colors.dim}"
    typography: "{typography.body}"
    rounded: "0"
    padding: "0 0 9px"
  subtab-active:
    backgroundColor: "transparent"
    textColor: "{colors.blue-hi}"
  target-item:
    backgroundColor: "transparent"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "9px 10px"
    width: "100%"
  target-item-active:
    backgroundColor: "#242933"
    textColor: "{colors.fg}"
  pill-ok:
    backgroundColor: "rgba(61,171,98,.14)"
    textColor: "#64c285"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  pill-bad:
    backgroundColor: "rgba(229,72,77,.14)"
    textColor: "#f0787c"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  pill-warn:
    backgroundColor: "rgba(224,162,60,.14)"
    textColor: "{colors.amber}"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  pill-flat:
    backgroundColor: "{colors.ctrl}"
    textColor: "{colors.dim}"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  note-danger:
    backgroundColor: "rgba(229,72,77,.08)"
    textColor: "#e9b6b8"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "10px 13px"
  note-calm:
    backgroundColor: "rgba(47,127,239,.08)"
    textColor: "#b9cdea"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "10px 13px"
  log-console:
    backgroundColor: "{colors.log-bg}"
    textColor: "{colors.log-ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.md}"
    padding: "13px 15px"
---

# Design System: Painel do Servidor

## Overview

**Creative North Star: "The Operator's Workbench"**

This is dark application chrome, not a metrics dashboard. The whole surface is built from three luminance steps — frame (#1a1b1e), card (#25262a), control (#2c2d33) — each separated by one step plus a 1px hairline. Nothing glows, nothing floats, nothing gradients. The screen reads as a tool that is permanently installed on a machine: a fixed 272px rail of targets on the left, a large target name with its live state on the right, the consequential buttons parked top-right, a resource strip underneath, then tabs and body. A short night-time session should resolve in one glance and one click.

The world is the category canon, chosen deliberately by the owner rather than invented: the craft bar is MC Server Manager (Natchland), recorded in `.impeccable/roll.json`. Fidelity to that reference is the standard, which is why the type is a neutral UI grotesque and the colour is almost entirely absent. Colour here is not decoration or branding; it is consequence. Blue acts, green starts, red stops or deletes, amber means partial or in transition. A surface with no pending consequence is grey, and that greyness is the product telling the truth: nothing needs you right now.

The system's second axis is risk, and risk is expressed in interaction rather than in hue. Production targets and whole-machine actions demand a typed confirmation; leisure targets ask once and get out of the way. Long operations disable their own trigger. Live regions refresh themselves, except where the user is typing. Visual calm plus interaction friction, applied exactly where the consequence is real.

**Key Characteristics:**
- Three chrome depths separated by one luminance step and a 1px line; no shadows, no gradients.
- Four fixed type steps (12 / 15 / 19 / 26px) and nothing in between.
- Colour only where an action has a consequence; everything else is neutral grey.
- Fixed 272px target rail with a state dot per target; single-column stack below 880px.
- 8px cards, 6px controls, 999px status pills; 1px borders everywhere instead of elevation.
- Self-hosted Inter (400 / 600 / 700) with no network dependency.

## Colors

A near-monochrome dark grey chrome with four strictly semantic accents, each of which means a consequence rather than a mood.

### Primary
- **Action Blue** (`{colors.blue}`): the only "do it" colour. Primary buttons (`.b-primary`), the active primary tab pill, the brand mark square, focus outlines, checkbox accent, and the underline of an active sub-tab. Never used to decorate a panel or a heading.
- **Link Blue** (`{colors.blue-hi}`): the lighter reading of the same hue, used for text that is blue — links and active sub-tab labels — and for the primary button's hover.
- **Deep Blue Edge** (`{colors.blue-dim}`): border-only. The selected target in the rail and the calm note's border; it marks selection without lighting it.

### Secondary
- **Go Green** (`{colors.green}`): starts things. `.b-go` buttons, the "no ar" state word, live state dots, and the healthy fill of a usage bar. Paired with near-black ink (#06230f) on solid fills so the green stays legible.
- **Stop Red** (`{colors.red}`): stops or deletes. Text and border of the ghost `.b-stop` button, danger notes, error flashes, and a usage bar past 90%.
- **Transition Amber** (`{colors.amber}`): partial or in-between. A stack with some containers up, a warn pill, a bar in the 75–90% band. Amber never means "pretty"; it means not-yet-settled.

### Tertiary
- **Edge Greens / Edge Reds** (`{colors.green-dim}`, `{colors.red-dim}`): the dim siblings exist only as 1px borders and tinted-fill companions, so a dangerous control can be outlined without being filled.

### Neutral
- **Frame** (`{colors.app}`): the page body, the outermost depth; also the track of a usage bar.
- **Rail** (`{colors.side}`): the fixed sidebar, one step off the frame.
- **Card** (`{colors.card}`): every card, stat tile, action row, and the resource strip.
- **Control** (`{colors.ctrl}`): buttons, inputs, selects, textareas, and the flat pill. Controls are the brightest surface because they are the thing you touch.
- **Line** / **Soft Line** (`{colors.line}`, `{colors.line-soft}`): the structural 1px border and the quieter internal divider (table rows, sidebar section edges, the sub-tab baseline).
- **Ink / Dim / Dimmer** (`{colors.fg}`, `{colors.dim}`, `{colors.dimmer}`): body text, secondary metadata and labels, and tertiary footnotes or placeholders.
- **Console Ink on Console Black** (`{colors.log-ink}` on `{colors.log-bg}`): log and RCON output sits darker than the frame, so machine text is visibly not chrome.

### Named Rules
**The Consequence Rule.** Colour is reserved for consequence: blue acts, green starts, red stops or deletes, amber transitions. If a pixel is coloured and nothing happens when you press it, that colour is a bug.

**The Tinted-Fill Rule.** Accent surfaces are a ~8–14% alpha wash of the accent plus a 1px accent-family border, never a saturated block. Pills use 14%, flashes 10%, notes 8%.

## Typography

**Display / Body / Label Font:** Inter (self-hosted, with `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` behind it)
**Mono Font:** `ui-monospace, SFMono-Regular, Menlo, monospace` — for container names, addresses, shell snippets, textareas, and log output

**Character:** A neutral UI grotesque, tightened slightly at the largest step (-0.02em) and left alone everywhere else. It has no opinion of its own, which is the point: the only thing on screen allowed to be expressive is a state word. Inter is self-hosted at `panel/static/inter-{400,600,700}.woff2` with `font-display:swap` because the machine's network filters font CDNs and the system stack would fall to Segoe UI, which is not the pinned reference's lettering. A saturated-pattern detector will flag Inter as an overused face; that finding is known and accepted here, because the pinned craft reference outranks it. Do not "fix" this by swapping the family.

### Hierarchy
- **Display** (700, 26px, 1.1, -0.02em): the target name in the header — one per screen, and the only large type in the system.
- **Title** (700, 19px, 1.2): stat tile values, tabular-nums on. Numbers are the headline of a monitoring surface, so the number gets the title step, not the label above it.
- **Body** (400, 15px, 1.5): everything readable — paragraphs, table cells, buttons, inputs, row titles (600), card headings (`h3`, 15px semibold). A card heading is body-sized and distinguished by weight, not size.
- **Label** (400, 12px, 1.6): field labels, card hints, metadata lines, hints, empty states, table headers (semibold, 0.03em), sub-states.
- **Badge** (700, 12px, 0.02em): status pills and the state word next to the target name.
- **Mono** (400, 12px, 1.65): log output, container names, addresses, textareas.

### Named Rules
**The Four Steps Rule.** The ramp is exactly four sizes — 12 / 15 / 19 / 26px, ratio ~1.25. An earlier build carried six near-identical sizes and it was corrected. Never introduce an intermediate step; separate things by weight or colour instead.

**The Tabular Numbers Rule.** Any number that refreshes in place (stat values, resource strip values, timestamps, process counts) carries `font-variant-numeric: tabular-nums` so a polling swap does not make the layout twitch.

## Layout

A two-column CSS grid shell at full height: a fixed `272px` rail and a `1fr` main column, each an independent `min-height:0` flex column so only the intended regions scroll. The body itself does not scroll on desktop (`overflow:hidden`); the rail list and the main body scroll separately.

The main column is a fixed header stack over one scrolling body: target header (`18px 24px 0`), resource strip, primary tabs, optional sub-tabs, then `.main-scroll` with `0 24px 28px`. `24px` is the frame gutter and is shared by the header, strip, tabs, sub-tabs, and flash so every left edge aligns.

Rhythm inside surfaces is tighter: `16px` card padding and the gap between cards and card stacks, `12–14px` row padding, `9px` between stacked rows and inline controls, `7px` between buttons in a cluster, `4–5px` under a label. Card grids are intrinsic, not breakpoint-driven: `repeat(auto-fit, minmax(300px, 1fr))` for content cards, `minmax(178px, 1fr)` for stat tiles, `minmax(190px, 1fr)` for form fields.

There is one breakpoint, `max-width: 880px`. Below it the shell collapses to a single column, the rail becomes a top band with its list capped at `230px`, the body gutter drops to `16px`, the header row stacks (name over full-width buttons), and header metadata flips from right-aligned to left. Scrolling moves back to the document.

### Named Rules
**The Buttons-Right Rule.** In any action row — target header, task row, container row, backup row — the description stays left in a `min-width:0` flex-1 block and the controls sit right in a `flex:0 0 auto` cluster. Status words and badges also get `flex:0 0 auto`; a squeezed label truncating "ligado" to "lig" is the failure this rule exists to prevent.

**The One Gutter Rule.** Every top-level band in the main column uses the same 24px horizontal gutter (16px under 880px). Nothing indents itself independently.

## Elevation & Depth

This system has no elevation. There are no gradients and no offset or drop shadows anywhere in the chrome. Depth is tonal: four stacked greys — frame, rail, card, control — each one luminance step apart and each separated by a 1px `{colors.line}` border. A card reads as above the frame because it is lighter *and* outlined, not because it casts anything. Console surfaces invert the move: they go *darker* than the frame to read as machine output rather than chrome.

### Shadow Vocabulary
- **State dot halo** (`box-shadow: 0 0 0 3px rgba(61,171,98,.16)` / `rgba(224,162,60,.16)`): the single legitimate shadow, and it is not a shadow — it is a flat concentric ring that makes a 9px live or transitioning dot visible at a glance in the rail. Stopped dots get no ring.

### Named Rules
**The No-Lift Rule.** Surfaces never lift. If something needs to read as separate, change its grey by one step and add a 1px line. The only `box-shadow` in the system is the state-dot ring.

**The Hairline Rule.** Structure is drawn with `1px solid {colors.line}`; internal dividers inside an already-bordered surface drop to `{colors.line-soft}`. Empty states use the same 1px at `dashed`.

## Shapes

Everything is a soft rectangle. Containers — cards, stat tiles, action rows, the resource strip, log blocks, flashes, empty states, rail items — use an 8px radius (`{rounded.md}`). Controls one tier smaller: buttons, inputs, selects, notes, tab pills at 6px (`{rounded.sm}`). Two exceptions by role: status pills are fully round (999px) because they are badges, not surfaces, and state dots are true circles at 9–10px. The brand mark is a 22px blue square at 5px radius; usage bars are 5px tall with a 3px radius. Sub-tabs have no radius at all — they are a 2px bottom border on a baseline, deliberately not a pill, so the two tab levels can never be confused.

## Components

### Buttons
- **Shape:** softly rounded (6px), inline-flex with a 7px gap for an adjacent spinner or badge, `white-space:nowrap`, `line-height:1.2`.
- **Neutral (default `button`, `.btn`):** control grey on a 1px line, body-size, `7px 13px`. The ambient verb.
- **Primary (`.b-primary`):** solid action blue, white ink, 600 weight. Reserved for the consequential-but-reversible verb (Reiniciar, Salvar, Entrar).
- **Go (`.b-go`):** solid green with near-black ink (#06230f), 600 weight. Starts things, only.
- **Stop (`.b-stop`):** transparent with a deep-red edge and red ink, filling to a 12% red wash on hover. Stopping is outlined, not shouted; a filled red button would weigh the same as a green one.
- **Small (`.b-sm`):** `4px 10px` at label size, for per-row and per-container controls.
- **Ghost (`.b-ghost`):** transparent background only; used for low-priority navigation and for values in the resource strip that double as a link into Settings.
- **Hover:** background `#34353c` / border `#45464e` on neutral, the lighter accent on filled variants; `background`, `border-color` and `color` transition over 140ms ease.
- **Focus:** `2px solid {colors.blue}` outline with 2px offset, on every interactive element including inputs. Never removed.
- **Disabled:** `opacity:.42`, `cursor:not-allowed`, hover suppressed. Disabled is how the system says "this verb does not apply to the current state" — a stopped target's Stop button is disabled, not hidden.

### Cards / Containers
- **Corner Style:** 8px.
- **Background / Border:** card grey with a 1px line.
- **Shadow Strategy:** none; see Elevation & Depth.
- **Internal Padding:** 16px, with a 15px/650 `h3` and an optional 12px dim `.card-hint` line under it, 13px of air before the content.
- **Stat tile:** a denser card (`14px 16px`) built as label (12px dim) over value (19px, tabular) over note (12px dimmer).
- **Action row:** card grey, 8px, `12px 14px`, info left and `.acts` right; an inactive row drops to `opacity:.55` rather than changing colour.

### Inputs / Fields
- **Style:** control grey, 1px line, 6px radius, `7px 10px`, full width by default, inheriting body size. Labels sit above at 12px dim with 5px of space.
- **Focus:** the same 2px blue outline at 2px offset as buttons; the field itself does not change colour.
- **Textarea:** mono at 12px / 1.6 — multi-line input in this product is always file or config content.

### Navigation
- **Target rail:** full-width transparent buttons with a transparent 1px border, 8px radius, `9px 10px`, state dot + two-line text block (15px/600 name over 12px dim subtitle) + right-aligned 12px state tag. Hover fills `#26272c`; the selected item fills `#242933` and takes a deep-blue border. The name and subtitle are `display:block` so they never collapse onto one line, and all three text parts truncate with ellipsis.
- **Primary tabs:** transparent, dim, 6px radius; the active tab becomes a solid blue pill with white ink.
- **Sub-tabs:** text-only on a soft-line baseline, 18px apart, dim by default, active becomes link-blue with a 2px blue bottom border. Two levels, two different shapes, no overlap in vocabulary.

### Status Pills
- **Style:** fully round, `2px 9px`, 12px/700 at 0.02em, a 14% accent wash with a lighter accent ink. Four variants: ok (green), bad (red), warn (amber), flat (control grey with dim ink for a neutral machine word like "exited").
- **State:** paired with the bare `.state` text treatment in the header (green / amber / dim) and the `.dot` in the rail. The same three-value state vocabulary — no-ar, parcial, parado — is rendered three ways by scale: dot in the rail, word in the header, pill in a table or row.

### Notices
- **`.note`:** a full 1px border all the way around with an 8% tinted fill, 6px radius, 12px/1.6 text. Danger is the default; `.note.calm` swaps to blue. This carries the hard warnings ("this stops the entire machine").
- **`.flash`:** the swap target for every action's result; 8px, 10% tinted fill with a 35% border, body size, in the frame gutter above the target.
- **`.empty`:** centred 12px dim text in a 1px dashed box with 26px of vertical air.

### Log / Console Surface
A `pre.log` at console black (#131417) with a 1px line, 8px radius, `13px 15px`, mono 12px/1.65, `max-height:52vh`, wrapping on `pre-wrap` + `break-word`. It is the one surface darker than the frame, which is exactly how the eye separates machine output from UI.

### Risk-Tiered Confirmation (signature pattern)
Risk is encoded in interaction, not colour. A production target (igenda, Supabase), "Desligar tudo", and host shutdown use `hx-prompt` demanding a typed phrase (the target's own label, or `DESLIGAR TUDO`), verified server-side. Leisure targets (Minecraft) and single-container actions use a plain `hx-confirm`. Every long operation carries `hx-disabled-elt="this"` so a second click cannot fire a duplicate job, and a `.spin` label ("gravando no host…") appears during the request via `.htmx-request`. In-flight cards drop to `opacity:.6`. The buttons themselves look identical across risk tiers — the friction is in the dialog, not the paint.

### Self-Refreshing Region (signature pattern)
Read-only regions wrap themselves in a polled element (`hx-trigger="every 5s/6s/8s/10s, panel-refresh from:body"`, `hx-swap="outerHTML"`), so state, uptime, memory and player counts age out on their own. Regions containing user input — time fields, the nick field, the config form, the file editor — are deliberately outside any polled wrapper. First paint is server-rendered: rail, header, tabs and the default tab body come inline from `index()`; HTMX owns every later swap.

## Do's and Don'ts

### Do:
- **Do** use colour only where there is a consequence: blue acts, green starts, red stops or deletes, amber is partial or in transition.
- **Do** build depth from the four greys (frame #1a1b1e → rail #1f2023 → card #25262a → control #2c2d33) plus a 1px `#35363d` line.
- **Do** stay on the four type steps: 12 / 15 / 19 / 26px. Separate peers by weight or by dim/fg, never by a new size.
- **Do** put the description left and the controls right in every action row, with `flex:0 0 auto` on the control cluster and on any state word.
- **Do** give every container 8px corners and every control 6px; pills are the only fully round shape.
- **Do** tint accent surfaces at ~8–14% alpha with a 1px accent-family border.
- **Do** add `hx-disabled-elt="this"` to any trigger that starts a long operation, and `tabular-nums` to any number that refreshes in place.
- **Do** demand a typed `hx-prompt` confirmation for production stacks and whole-machine actions; a plain `hx-confirm` for leisure.
- **Do** keep self-hosted Inter 400/600/700 as the only face; its being a common UI font is an accepted, recorded finding, not a defect to fix.
- **Do** use the one 880px breakpoint: single column, 16px gutter, stacked header with full-width buttons.

### Don't:
- **Don't** add gradients, drop shadows, or offset shadows. The only `box-shadow` in the system is the flat 3px state-dot ring.
- **Don't** give `.note`, cards, or banners a one-sided coloured accent bar. A notice gets a full 1px border and a tinted fill.
- **Don't** introduce an intermediate font size (13px, 14px, 17px, 22px). Six near-identical sizes was the previous build's defect and it was corrected.
- **Don't** colour anything decoratively — no accent headings, no coloured card edges to signal category, no branded tint on a neutral surface.
- **Don't** fill a destructive button solid. Stop stays transparent with a red edge; only Go and Primary are solid.
- **Don't** hide a verb that does not currently apply — disable it at `opacity:.42` so the state stays legible.
- **Don't** put a text input, time field, or form inside an `hx-trigger="every Ns"` wrapper; a poll mid-typing destroys what the user typed.
- **Don't** make primary tabs and sub-tabs look alike: primary is a blue pill, sub is an underline on a baseline.
- **Don't** let a two-line rail item's name and subtitle be inline spans; they are `display:block` or they collapse onto one line.
- **Don't** reach for a second typeface, an icon font, or glyph icons as decoration; the system carries no icon set at all.
