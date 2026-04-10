# BRD-04: Design System

## Aesthetic Identity

The Trading Floor uses a Vercel/Linear developer-luxury aesthetic applied to a trading terminal.
The visual language communicates: precision, power, and trust. It feels like a tool built for
professionals, not a retail app.

Key characteristics:
- Cool-neutral dark surfaces (not warm black, not pure #000)
- Tight letter-spacing: -0.04em on UI text, -0.02em on mono data
- Opacity-based elevation hierarchy (surfaces defined by alpha, not brightness)
- Frosted glass for floating panels
- Astro UXDS status colors for all operational states

---

## CSS Custom Properties

All design tokens are defined as CSS custom properties on `:root` in `globals.css`.

### Background Colors

| Token | Value | Usage |
|-------|-------|-------|
| `--bg-void` | `#0A0D13` | Page background, deepest layer |
| `--bg-base` | `#0F1219` | App background, behind all panels |
| `--bg-surface-1` | `#171B24` | Primary panel backgrounds (cards, sidebars) |
| `--bg-surface-2` | `#1F2430` | Secondary panel backgrounds, nested containers |
| `--bg-surface-3` | `#292E38` | Tertiary surfaces, input backgrounds |
| `--bg-hover` | `#313742` | Hover state for interactive surface elements |
| `--glass-bg` | `rgba(255,255,255,0.03)` | Base fill for frosted glass panels |

Elevation is created by the stack of surface colors. The deepest background (`--bg-void`) is
the darkest. Each surface layer uses opacity-based tints rather than lightness adjustment,
which preserves the cool-neutral character at all depths.

### Text Colors

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#EEEFF1` | Body text, headings, active labels |
| `--text-secondary` | `rgba(238,239,241,0.65)` | Subtext, metadata, descriptions |
| `--text-tertiary` | `rgba(238,239,241,0.40)` | Hints, placeholders, inactive tabs |
| `--text-disabled` | `rgba(238,239,241,0.25)` | Disabled inputs, locked controls |

Text color is opacity-based on a single base value (`#EEEFF1`), not distinct hues. This
preserves visual harmony across all surface backgrounds.

### Border Colors

| Token | Value | Usage |
|-------|-------|-------|
| `--border-subtle` | `rgba(255,255,255,0.05)` | Hairline dividers, table row borders |
| `--border-default` | `rgba(255,255,255,0.08)` | Panel borders, card outlines |
| `--border-emphasis` | `rgba(255,255,255,0.12)` | Focused input borders, selected items |
| `--border-top-highlight` | `rgba(255,255,255,0.10)` | Top edge of glass panels (light catch) |

### Spacing Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--space-1` | `4px` | Icon gaps, tight padding |
| `--space-2` | `8px` | Compact element padding |
| `--space-3` | `12px` | Default inner padding |
| `--space-4` | `16px` | Standard element padding |
| `--space-6` | `24px` | Section padding |
| `--space-8` | `32px` | Page-level padding |

### Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | `6px` | Badges, chips, small buttons |
| `--radius-md` | `10px` | Input fields, medium buttons |
| `--radius-lg` | `12px` | Cards, panels |
| `--radius-xl` | `16px` | Modal dialogs, large panels |

### Shadow Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-1` | `0 1px 2px rgba(0,0,0,0.5), 0 2px 4px rgba(0,0,0,0.4)` | Subtle lift on hover |
| `--shadow-2` | `0 2px 4px rgba(0,0,0,0.4), 0 8px 16px rgba(0,0,0,0.3)` | Cards, dropdowns |
| `--shadow-3` | `0 4px 8px rgba(0,0,0,0.35), 0 16px 32px rgba(0,0,0,0.25)` | Modals, top-level panels |

---

## Astro UXDS Status Colors

The Astro Space UX Design System defines operational status colors used in mission-critical
interfaces. The Trading Floor adopts these exactly for all operational states.

| Token | Hex | Meaning | Use Case |
|-------|-----|---------|----------|
| `--status-critical` | `#FF3838` | Immediate action required | Kill switch triggered, daily loss breached, agent crash |
| `--status-serious` | `#FFB302` | Prompt attention required | Near daily loss limit, signal rejection rate high |
| `--status-caution` | `#FCE83A` | Awareness required | Agent latency degraded, low confidence signal |
| `--status-normal` | `#56F000` | All systems nominal | Agent healthy, trade filled, system operating |
| `--status-standby` | `#2DCCFF` | Ready, not active | Agent idle and available, COMMANDER mode |
| `--status-off` | `#A4ABB6` | Not in use | Agent disabled, market closed |

### Accent Colors

| Token | Value | Usage |
|-------|-------|-------|
| `--accent-primary` | `#5E6AD2` | Primary interactive elements, focus rings, selection |
| `--accent-cyan` | `#2DCCFF` | Secondary highlights, links, data callouts |
| `--accent-profit` | `#58D68D` | Positive P&L, long signals, profitable trades |
| `--accent-loss` | `#F85149` | Negative P&L, short signals, losing trades |

---

## Typography

### Fonts

`--font-sans: 'Geist', -apple-system, system-ui, sans-serif`

Geist is Vercel's design system font. It has tight letter-spacing (-0.04em default for UI text)
and excellent legibility at small sizes. Used for all UI text: labels, headings, body, buttons.

`--font-mono: 'JetBrains Mono', 'SF Mono', monospace`

JetBrains Mono is used for all data: prices, timestamps, order IDs, hashes, log output, code.
It has excellent legibility at 11-13px, which is required for dense data tables.

### Type Scale

```css
/* Headings */
.heading-1 { font-size: 24px; font-weight: 600; letter-spacing: -0.04em; }
.heading-2 { font-size: 18px; font-weight: 600; letter-spacing: -0.03em; }
.heading-3 { font-size: 14px; font-weight: 600; letter-spacing: -0.02em; }

/* Body */
.body-base  { font-size: 13px; font-weight: 400; letter-spacing: -0.01em; }
.body-small { font-size: 11px; font-weight: 400; letter-spacing: 0; }

/* Mono data */
.data-base  { font-family: var(--font-mono); font-size: 13px; letter-spacing: -0.02em; }
.data-small { font-family: var(--font-mono); font-size: 11px; letter-spacing: 0; }
```

---

## Monument Valley Isometric Agent Design

### Grid Specification

The PixiJS trading floor uses a standard isometric projection:
- 30-degree isometric angle (2:1 pixel ratio for tile faces)
- Tile width: 64px, tile height: 32px
- Agent desk tile: 2x2 grid tiles (128x64px footprint)

### Agent Character Proportions

Each agent sprite is 32x48px rendered at 2x for retina (64x96px source).

```
Head: 16x16px, centered, 3-tone shading
Body: 12x20px, centered below head, 3-tone shading
Desk: 32x16px, isometric tile under sprite
Status ring: 2px border around desk tile base
```

### 3-Tone Face Shading

Each face (front, top, side) of isometric elements uses 3 tones:
- Highlight: base color at 100% brightness (top face, light source)
- Base: base color at 75% brightness (front face)
- Shadow: base color at 50% brightness (right side face, away from light)

Agent color palette (one per agent):

| Agent | Base Color |
|-------|-----------|
| Marcus | `#4A90D9` (blue) |
| Vera | `#7B68EE` (purple) |
| Rex | `#E8A838` (amber) |
| Diana | `#E84040` (red) |
| Atlas | `#40B8A8` (teal) |
| Nova | `#8B5CF6` (violet) |
| Bull | `#40C868` (green) |
| Bear | `#E85040` (orange-red) |
| Sage | `#F0C040` (gold) |
| Scout | `#60C8E8` (sky) |

---

## Visual Effect Patterns

### Frosted Glass Panel

The `.glass-panel` class creates frosted glass containers for floating panels, modals, and
tooltips.

```css
.glass-panel {
  background: rgba(255, 255, 255, 0.03);
  backdrop-filter: blur(12px) saturate(150%);
  -webkit-backdrop-filter: blur(12px) saturate(150%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-top-color: rgba(255, 255, 255, 0.10);
  border-radius: 12px;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.03) inset,
    0 8px 32px rgba(0, 0, 0, 0.4);
}
```

The top border is slightly brighter than side/bottom borders, simulating a light catch from
the ambient scene. The inner inset shadow adds subtle depth.

### Aurora Gradient Background

The page background uses three blurred blobs composited with `mix-blend-mode: screen`:

```css
.aurora-bg {
  position: fixed;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.aurora-blob-1 {
  position: absolute;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(94, 106, 210, 0.15) 0%, transparent 70%);
  filter: blur(80px);
  top: -200px;
  left: -100px;
  mix-blend-mode: screen;
}

.aurora-blob-2 {
  position: absolute;
  width: 500px;
  height: 500px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(45, 204, 255, 0.10) 0%, transparent 70%);
  filter: blur(80px);
  top: 40%;
  right: -150px;
  mix-blend-mode: screen;
}

.aurora-blob-3 {
  position: absolute;
  width: 400px;
  height: 400px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(64, 184, 168, 0.08) 0%, transparent 70%);
  filter: blur(80px);
  bottom: -100px;
  left: 40%;
  mix-blend-mode: screen;
}
```

### Noise Texture Overlay

A subtle noise texture breaks up flat dark surfaces. Applied as an SVG feTurbulence filter
at 4% opacity with soft-light blend mode.

```css
.noise-overlay {
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: 0.04;
  mix-blend-mode: soft-light;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-size: 200px 200px;
}
```

### Gradient Border Technique

Gradient borders on panels use the double-layer background-clip technique:

```css
.gradient-border {
  position: relative;
  border-radius: var(--radius-lg);
  background-clip: padding-box;
}

.gradient-border::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: calc(var(--radius-lg) + 1px);
  background: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.12) 0%,
    rgba(255, 255, 255, 0.04) 40%,
    rgba(94, 106, 210, 0.20) 100%
  );
  z-index: -1;
}
```

### Status Indicator Glow

Operational status indicators use a 3-layer box-shadow glow:

```css
/* CRITICAL status glow */
.status-critical-glow {
  box-shadow:
    0 0 0 1px #FF3838,
    0 0 4px rgba(255, 56, 56, 0.6),
    0 0 12px rgba(255, 56, 56, 0.3);
}

/* NORMAL status glow */
.status-normal-glow {
  box-shadow:
    0 0 0 1px #56F000,
    0 0 4px rgba(86, 240, 0, 0.6),
    0 0 12px rgba(86, 240, 0, 0.3);
}
```

Layer 1: Solid 1px ring at full color.
Layer 2: 4px soft glow at 60% opacity.
Layer 3: 12px ambient glow at 30% opacity.

The same pattern applies for all 6 Astro UXDS status colors.
