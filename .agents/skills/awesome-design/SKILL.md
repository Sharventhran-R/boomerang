---
name: awesome-design
description: |
  Curated collection of DESIGN.md files from real websites. Each DESIGN.md contains
  complete design system specifications including color palette, typography, component
  styles, spacing, and visual guidelines that AI agents can use to generate
  pixel-perfect UI matching the source website's design.
  Use when: user wants to create UI that looks like a specific website (e.g., "build
  a page like Notion", "make it look like Linear's design"), or needs design tokens
  and component specifications for a particular design style. Also use when the user
  needs to browse or compare the design library visually before choosing a DESIGN.md.
license: MIT
metadata:
  version: "1.0.0"
  category: design
  sources:
    - https://github.com/VoltAgent/awesome-design-md
---

# Awesome DESIGN.md

A curated collection of 55+ DESIGN.md files extracted from real websites, based on Google's Stitch DESIGN.md format.

## Available Design Systems

### AI & Machine Learning
| Site | Style |
|------|-------|
| Claude | Warm terracotta, editorial layout |
| Cohere | Vibrant gradients, data-rich dashboard |
| ElevenLabs | Dark cinematic, audio-waveform aesthetics |
| Minimax | Bold dark, neon accents |
| Mistral AI | French minimalism, purple-toned |
| Ollama | Terminal-first, monochrome |
| xAI | Stark monochrome, futuristic |

### Developer Tools & Platforms
| Site | Style |
|------|-------|
| Cursor | AI-first code editor, gradient accents |
| Linear | Ultra-minimal, precise, purple accent |
| Vercel | Black/white precision, Geist font |
| Raycast | Sleek dark, vibrant gradients |
| Supabase | Dark emerald, code-first |
| Expo | Dark theme, code-centric |
| Mintlify | Clean green, reading-optimized |
| PostHog | Playful hedgehog, developer-friendly dark |

### Design & Productivity
| Site | Style |
|------|-------|
| Figma | Vibrant multi-color, playful yet professional |
| Notion | Warm minimalism, serif headings |
| Framer | Bold black and blue, motion-first |
| Miro | Bright yellow, infinite canvas |
| Webflow | Blue-accented, polished marketing |

### Fintech & Crypto
| Site | Style |
|------|-------|
| Coinbase | Clean blue, trust-focused |
| Revolut | Sleek dark, gradient cards |
| Wise | Bright green, friendly clear |

### Enterprise & Consumer
| Site | Style |
|------|-------|
| Airbnb | Warm coral, photography-driven |
| Apple | Premium white space, SF Pro |
| Spotify | Vibrant green on dark |
| NVIDIA | Green-black energy, technical |

## How to Use

### 1. Open the Preview Library First
Build the local visual catalog when the user needs to compare styles before choosing:

```powershell
python scripts/build_preview_library.py --open
```

This generates `preview-library/index.html`, which aggregates the existing
`preview.html` and `preview-dark.html` files for the whole collection.

### 2. Compare Designs Visually
Use the preview library to:

- scan the overall vibe of each site
- compare light and dark previews
- open the matching `DESIGN.md` only after the visual direction is clear

### 3. Use the Built-in Prompt Composer
After picking a card, click `Use This Design` in the preview library.

The local preview library now includes a selection studio that can:

- lock the chosen design into a composer panel
- show the exact local `DESIGN.md` path
- generate ready-to-send prompts for Codex, Claude Code, or a generic coding agent
- keep the design choice, task type, surface, and product brief together

### 4. Copy Design File
Copy the desired `DESIGN.md` file into the user's project root:
```
design-md/{site-name}/DESIGN.md
```

### 5. Apply Design
Either use the generated prompt from the preview library, or tell the user to instruct their AI agent:

"Use the DESIGN.md in your project to build UI that matches this design system."

## Preview Assets

Every site folder already includes:

- `DESIGN.md`
- `preview.html`
- `preview-dark.html`

The preview library is the top-level chooser and prompt generator that makes these usable at scale.

## Design System Contents

Each DESIGN.md includes:
1. **Visual Theme & Atmosphere** - Mood, density, philosophy
2. **Color Palette & Roles** - Semantic names + hex + functional role
3. **Typography Rules** - Font families, hierarchy table
4. **Component Stylings** - Buttons, cards, inputs, navigation
5. **Layout Principles** - Spacing scale, grid, whitespace
6. **Depth & Elevation** - Shadow system, surface hierarchy
7. **Do's and Don'ts** - Design guardrails
8. **Responsive Behavior** - Breakpoints, touch targets
9. **Agent Prompt Guide** - Ready-to-use prompts

## Locations

All design files are stored in:
```
design-md/{site-name}/DESIGN.md
```
