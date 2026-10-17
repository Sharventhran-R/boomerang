#!/usr/bin/env python3
"""Build a local visual catalog and prompt composer for awesome-design."""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import sys
import webbrowser

README_ENTRY_RE = re.compile(
    r"^- \[\*\*(?P<name>.+?)\*\*\]\((?P<url>https://github\.com/VoltAgent/awesome-design-md/tree/main/design-md/(?P<slug>[^/]+)/?)\) - (?P<summary>.+)$"
)
TITLE_RE = re.compile(r"^#\s+Design System:\s*(.+)$", re.MULTILINE)
HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
RGBA_COLOR_RE = re.compile(r"rgba?\([^)]+\)")


@dataclass
class DesignEntry:
    slug: str
    display_name: str
    category: str
    summary: str
    title: str
    design_path: Path
    preview_path: Path
    preview_dark_path: Path | None
    colors: list[str]


def parse_readme_metadata(readme_path: Path) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    current_category = "Uncategorized"
    for line in readme_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            current_category = line[4:].strip()
            continue
        match = README_ENTRY_RE.match(line.strip())
        if not match:
            continue
        slug = match.group("slug")
        metadata[slug] = {
            "display_name": match.group("name").strip(),
            "category": current_category,
            "summary": match.group("summary").strip(),
        }
    return metadata


def infer_title(design_md_path: Path) -> str:
    text = design_md_path.read_text(encoding="utf-8")
    match = TITLE_RE.search(text)
    if match:
        return match.group(1).strip()
    return design_md_path.parent.name.replace(".", " ").title()


def infer_summary(design_md_path: Path) -> str:
    text = design_md_path.read_text(encoding="utf-8")
    marker = "## 1. Visual Theme & Atmosphere"
    if marker not in text:
        return "Real-world design system preview."
    tail = text.split(marker, 1)[1]
    paragraphs = [part.strip().replace("\n", " ") for part in tail.split("\n\n")]
    for paragraph in paragraphs:
        if paragraph and not paragraph.startswith("**Key Characteristics:**"):
            return paragraph
    return "Real-world design system preview."


def extract_colors(preview_path: Path) -> list[str]:
    preview_text = preview_path.read_text(encoding="utf-8", errors="ignore")
    header = "\n".join(preview_text.splitlines()[:120])
    colors: list[str] = []
    seen: set[str] = set()
    for pattern in (HEX_COLOR_RE, RGBA_COLOR_RE):
        for match in pattern.findall(header):
            color = match.strip()
            if color.lower() in seen:
                continue
            seen.add(color.lower())
            colors.append(color)
            if len(colors) == 6:
                return colors
    return colors


def collect_designs(skill_root: Path) -> list[DesignEntry]:
    metadata_by_slug = parse_readme_metadata(skill_root / "README.md")
    design_root = skill_root / "design-md"
    entries: list[DesignEntry] = []

    for folder in sorted(path for path in design_root.iterdir() if path.is_dir()):
        design_path = folder / "DESIGN.md"
        preview_path = folder / "preview.html"
        if not design_path.is_file() or not preview_path.is_file():
            continue

        slug = folder.name
        meta = metadata_by_slug.get(slug, {})
        display_name = meta.get("display_name") or infer_title(design_path)
        category = meta.get("category") or "Uncategorized"
        summary = meta.get("summary") or infer_summary(design_path)
        preview_dark_path = folder / "preview-dark.html"

        entries.append(
            DesignEntry(
                slug=slug,
                display_name=display_name,
                category=category,
                summary=summary,
                title=infer_title(design_path),
                design_path=design_path,
                preview_path=preview_path,
                preview_dark_path=preview_dark_path if preview_dark_path.is_file() else None,
                colors=extract_colors(preview_path),
            )
        )

    return entries


def card_markup(entry: DesignEntry) -> str:
    category = html.escape(entry.category)
    display_name = html.escape(entry.display_name)
    title = html.escape(entry.title)
    summary = html.escape(entry.summary)
    slug = html.escape(entry.slug)
    preview_rel = html.escape(Path("..", "design-md", entry.slug, "preview.html").as_posix())
    preview_dark_rel = (
        html.escape(Path("..", "design-md", entry.slug, "preview-dark.html").as_posix())
        if entry.preview_dark_path
        else ""
    )
    design_rel = html.escape(Path("..", "design-md", entry.slug, "DESIGN.md").as_posix())
    color_swatches = "".join(
        f'<span class="swatch" style="background:{html.escape(color)}" title="{html.escape(color)}"></span>'
        for color in entry.colors[:5]
    )
    search_blob = html.escape(
        " ".join([entry.display_name, entry.slug, entry.category, entry.summary, entry.title]).lower()
    )
    dark_button = (
        f'<a class="action action-secondary" href="{preview_dark_rel}" target="_blank" rel="noreferrer">Dark Preview</a>'
        if preview_dark_rel
        else '<span class="action action-muted">Dark Preview N/A</span>'
    )

    return f"""
    <article class="design-card" data-category="{category}" data-search="{search_blob}" data-slug="{slug}">
      <div class="card-top">
        <span class="pill">{category}</span>
        <span class="slug">{slug}</span>
      </div>
      <div class="mini-browser">
        <div class="browser-chrome">
          <span></span><span></span><span></span>
        </div>
        <div class="preview-frame">
          <iframe loading="lazy" src="{preview_rel}" title="{display_name} light preview"></iframe>
        </div>
      </div>
      <div class="card-body">
        <h2>{display_name}</h2>
        <p class="title">{title}</p>
        <p class="summary">{summary}</p>
        <div class="swatches">{color_swatches}</div>
      </div>
      <div class="card-actions">
        <button class="action action-primary" type="button" data-action="choose" data-slug="{slug}">Use This Design</button>
        <a class="action action-outline" href="{design_rel}" target="_blank" rel="noreferrer">Open DESIGN.md</a>
        <a class="action action-secondary" href="{preview_rel}" target="_blank" rel="noreferrer">Light Preview</a>
        {dark_button}
      </div>
    </article>
    """.strip()


def catalog_payload(entries: list[DesignEntry]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for entry in entries:
        payload.append(
            {
                "slug": entry.slug,
                "display_name": entry.display_name,
                "category": entry.category,
                "summary": entry.summary,
                "title": entry.title,
                "design_md": Path("..", "design-md", entry.slug, "DESIGN.md").as_posix(),
                "preview": Path("..", "design-md", entry.slug, "preview.html").as_posix(),
                "preview_dark": (
                    Path("..", "design-md", entry.slug, "preview-dark.html").as_posix()
                    if entry.preview_dark_path
                    else None
                ),
                "colors": entry.colors,
            }
        )
    return payload


def render_html(entries: list[DesignEntry], skill_root: Path) -> str:
    categories = sorted({entry.category for entry in entries})
    category_buttons = "".join(
        f'<button class="filter-chip" type="button" data-category="{html.escape(category)}">{html.escape(category)}</button>'
        for category in categories
    )
    cards = "\n".join(card_markup(entry) for entry in entries)
    count = len(entries)
    payload_json = json.dumps(catalog_payload(entries), ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Awesome Design Preview Library</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --bg-accent: #ebe2d3;
      --surface: rgba(255, 251, 245, 0.90);
      --surface-strong: #fffaf2;
      --surface-deep: #f8f0e4;
      --border: rgba(87, 62, 36, 0.16);
      --text: #1e1a16;
      --muted: #615447;
      --accent: #b7602f;
      --accent-strong: #8d4c24;
      --accent-soft: #f3d9c6;
      --shadow: 0 18px 60px rgba(66, 43, 22, 0.12);
      --shadow-card: 0 14px 32px rgba(64, 44, 24, 0.09);
      --ring: 0 0 0 4px rgba(183, 96, 47, 0.14);
      --serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      --sans: "Aptos", "Segoe UI Variable Text", "Trebuchet MS", sans-serif;
      --mono: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{
      font-family: var(--sans);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.72), transparent 28rem),
        radial-gradient(circle at top right, rgba(183,96,47,0.10), transparent 22rem),
        linear-gradient(180deg, #f6f2ea 0%, #f2eadf 100%);
    }}
    button,
    input,
    select,
    textarea {{
      font: inherit;
    }}
    .shell {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 40px 24px 72px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      gap: 20px;
      align-items: stretch;
      margin-bottom: 24px;
    }}
    .hero-panel,
    .workflow,
    .studio,
    .controls {{
      background: var(--surface);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: 28px;
      box-shadow: var(--shadow);
    }}
    .hero-panel {{
      padding: 34px 34px 30px;
    }}
    .workflow {{
      padding: 28px;
    }}
    .eyebrow {{
      display: inline-flex;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }}
    h1,
    h2,
    h3 {{
      font-family: var(--serif);
      letter-spacing: -0.04em;
      margin: 0;
    }}
    h1 {{
      margin-top: 18px;
      font-size: clamp(2.6rem, 5vw, 4.8rem);
      line-height: 0.95;
    }}
    .hero-copy {{
      max-width: 70ch;
      margin-top: 14px;
      font-size: 18px;
      line-height: 1.7;
      color: var(--muted);
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 22px;
    }}
    .hero-stat {{
      padding: 12px 14px;
      border-radius: 18px;
      background: rgba(255,255,255,0.6);
      border: 1px solid rgba(87, 62, 36, 0.10);
      min-width: 130px;
    }}
    .hero-stat strong {{
      display: block;
      font-size: 20px;
      margin-bottom: 4px;
    }}
    .hero-stat span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .workflow h2 {{
      font-size: 30px;
      margin-bottom: 14px;
    }}
    .workflow p {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.65;
    }}
    .workflow ol {{
      margin: 16px 0 0 20px;
      padding: 0;
      color: var(--text);
      line-height: 1.85;
    }}
    .studio {{
      margin-bottom: 24px;
      padding: 22px;
      background:
        radial-gradient(circle at top right, rgba(183,96,47,0.08), transparent 20rem),
        linear-gradient(180deg, rgba(255,250,242,0.95), rgba(251,245,235,0.92));
    }}
    .studio-header {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: end;
      justify-content: space-between;
      margin-bottom: 18px;
    }}
    .studio-copy {{
      max-width: 70ch;
      color: var(--muted);
      line-height: 1.7;
      margin-top: 10px;
    }}
    .studio-layout {{
      display: grid;
      grid-template-columns: minmax(300px, 0.85fr) minmax(0, 1.15fr);
      gap: 18px;
    }}
    .selected-panel,
    .composer-panel {{
      border-radius: 24px;
      border: 1px solid rgba(87, 62, 36, 0.12);
      background: rgba(255,255,255,0.58);
      box-shadow: var(--shadow-card);
    }}
    .selected-panel {{
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .selected-placeholder {{
      min-height: 240px;
      display: grid;
      place-items: center;
      text-align: center;
      color: var(--muted);
      border-radius: 18px;
      border: 1px dashed rgba(87, 62, 36, 0.18);
      background: rgba(255,250,242,0.66);
      padding: 24px;
      line-height: 1.7;
    }}
    .selected-card {{
      display: none;
      flex-direction: column;
      gap: 14px;
    }}
    .selected-card.visible {{
      display: flex;
    }}
    .selected-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
    }}
    .selected-top h3 {{
      font-size: 32px;
      line-height: 1.02;
    }}
    .selected-subtitle {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .selected-summary {{
      margin: 0;
      line-height: 1.7;
    }}
    .selected-swatches {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .path-box {{
      padding: 14px;
      border-radius: 16px;
      background: var(--surface-deep);
      border: 1px solid rgba(87, 62, 36, 0.12);
    }}
    .path-label {{
      display: block;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 8px;
    }}
    .path-value {{
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.6;
      word-break: break-all;
      color: var(--text);
    }}
    .selected-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .composer-panel {{
      padding: 20px;
    }}
    .segmented {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 18px;
    }}
    .segment {{
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(87, 62, 36, 0.14);
      background: rgba(255,255,255,0.76);
      color: var(--text);
      cursor: pointer;
      transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease;
    }}
    .segment:hover {{
      transform: translateY(-1px);
    }}
    .segment.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff7f1;
    }}
    .composer-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .field {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .field-wide {{
      grid-column: 1 / -1;
    }}
    .field label,
    .field-label {{
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--accent);
    }}
    .select,
    .textarea {{
      width: 100%;
      border-radius: 16px;
      border: 1px solid rgba(87, 62, 36, 0.12);
      background: rgba(255,255,255,0.78);
      color: var(--text);
      padding: 14px 15px;
      outline: none;
      box-shadow: none;
    }}
    .select:focus,
    .textarea:focus {{
      border-color: rgba(183, 96, 47, 0.44);
      box-shadow: var(--ring);
    }}
    .textarea {{
      min-height: 118px;
      resize: vertical;
      line-height: 1.6;
    }}
    .prompt-output {{
      min-height: 300px;
      font-family: var(--mono);
      font-size: 13px;
      background: #fffdf8;
    }}
    .builder-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 18px 0;
    }}
    .controls {{
      position: sticky;
      top: 0;
      z-index: 12;
      margin-bottom: 24px;
      padding: 18px;
      background: rgba(255, 250, 242, 0.9);
    }}
    .search-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      margin-bottom: 14px;
    }}
    .search {{
      flex: 1 1 320px;
      min-width: 260px;
      padding: 16px 18px;
      font: inherit;
      font-size: 16px;
      border-radius: 18px;
      border: 1px solid rgba(87, 62, 36, 0.12);
      background: rgba(255,255,255,0.75);
      color: var(--text);
      outline: none;
    }}
    .search:focus {{
      border-color: rgba(183, 96, 47, 0.45);
      box-shadow: var(--ring);
    }}
    .results {{
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .filter-chip {{
      border: 1px solid rgba(87, 62, 36, 0.12);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
      font-size: 14px;
      transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease;
    }}
    .filter-chip:hover {{
      transform: translateY(-1px);
      border-color: rgba(183, 96, 47, 0.24);
    }}
    .filter-chip.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff7f1;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
    }}
    .design-card {{
      display: flex;
      flex-direction: column;
      min-height: 100%;
      background: rgba(255, 251, 245, 0.92);
      border: 1px solid rgba(87, 62, 36, 0.12);
      border-radius: 24px;
      box-shadow: var(--shadow-card);
      overflow: hidden;
      transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
    }}
    .design-card:hover {{
      transform: translateY(-3px);
    }}
    .design-card.selected {{
      border-color: rgba(183, 96, 47, 0.42);
      box-shadow: 0 20px 40px rgba(108, 62, 30, 0.18);
      transform: translateY(-3px);
    }}
    .card-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 16px 18px 0;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(183, 96, 47, 0.10);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }}
    .slug {{
      font-size: 12px;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .mini-browser {{
      margin: 14px 18px 0;
      border-radius: 18px;
      overflow: hidden;
      border: 1px solid rgba(87, 62, 36, 0.12);
      background: #fbf5ec;
    }}
    .browser-chrome {{
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 10px 12px;
      background: linear-gradient(180deg, rgba(240,231,219,0.96), rgba(232,223,211,0.96));
      border-bottom: 1px solid rgba(87, 62, 36, 0.10);
    }}
    .browser-chrome span {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: rgba(87, 62, 36, 0.18);
    }}
    .preview-frame {{
      position: relative;
      height: 230px;
      overflow: hidden;
      background: #ffffff;
    }}
    .preview-frame iframe {{
      width: 1280px;
      height: 900px;
      border: 0;
      transform: scale(0.29);
      transform-origin: top left;
      pointer-events: none;
    }}
    .card-body {{
      padding: 18px;
    }}
    .card-body h2 {{
      font-size: 31px;
      line-height: 1.02;
    }}
    .title {{
      margin: 8px 0 10px;
      font-size: 14px;
      color: var(--muted);
    }}
    .summary {{
      margin: 0;
      color: var(--text);
      line-height: 1.65;
      font-size: 15px;
    }}
    .swatches {{
      display: flex;
      gap: 8px;
      margin-top: 16px;
      flex-wrap: wrap;
    }}
    .swatch {{
      width: 22px;
      height: 22px;
      border-radius: 999px;
      border: 1px solid rgba(0, 0, 0, 0.08);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.14);
    }}
    .card-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 0 18px 18px;
      margin-top: auto;
    }}
    .action {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      padding: 10px 14px;
      border-radius: 12px;
      text-decoration: none;
      font-size: 14px;
      font-weight: 700;
      border: 1px solid transparent;
      cursor: pointer;
    }}
    .action-primary {{
      background: var(--accent);
      color: #fff8f1;
    }}
    .action-secondary {{
      background: rgba(183, 96, 47, 0.10);
      color: var(--accent);
      border-color: rgba(183, 96, 47, 0.12);
    }}
    .action-outline {{
      background: transparent;
      color: var(--text);
      border-color: rgba(87, 62, 36, 0.16);
    }}
    .action-muted {{
      background: rgba(87, 62, 36, 0.08);
      color: var(--muted);
      border-color: rgba(87, 62, 36, 0.08);
      cursor: default;
    }}
    .action-copy {{
      background: var(--surface-deep);
      color: var(--text);
      border-color: rgba(87, 62, 36, 0.16);
    }}
    .status {{
      min-height: 22px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
    }}
    .empty {{
      display: none;
      padding: 48px 22px;
      text-align: center;
      color: var(--muted);
      font-size: 16px;
    }}
    @media (max-width: 1180px) {{
      .hero,
      .studio-layout {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 820px) {{
      .composer-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 720px) {{
      .shell {{
        padding: 24px 16px 40px;
      }}
      .hero-panel,
      .workflow,
      .studio,
      .controls,
      .selected-panel,
      .composer-panel {{
        border-radius: 20px;
      }}
      .hero-panel,
      .workflow,
      .studio,
      .composer-panel,
      .selected-panel {{
        padding: 20px;
      }}
      .preview-frame {{
        height: 200px;
      }}
      .preview-frame iframe {{
        transform: scale(0.24);
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="hero-panel">
        <span class="eyebrow">Visual Selection Layer</span>
        <h1>Choose the design by seeing it, then turn it into a ready-to-send agent prompt.</h1>
        <p class="hero-copy">
          This library is the front door to `awesome-design`. Browse the real previews, lock in a visual direction,
          then use the built-in composer to generate a prompt for Codex, Claude Code, or a generic coding agent.
        </p>
        <div class="hero-meta">
          <div class="hero-stat"><strong>{count}</strong><span>design systems</span></div>
          <div class="hero-stat"><strong>Prompt Composer</strong><span>Codex, Claude, and generic modes</span></div>
          <div class="hero-stat"><strong>Local</strong><span>preview and DESIGN.md paths stay on your machine</span></div>
        </div>
      </div>
      <aside class="workflow">
        <h2>Recommended Flow</h2>
        <p>Start with visual comparison, not prose. The goal is to choose a direction with confidence before any frontend work begins.</p>
        <ol>
          <li>Search by brand, mood, category, or product type.</li>
          <li>Open the light or dark preview at full size when a card looks promising.</li>
          <li>Click <strong>Use This Design</strong> to send that style into the composer.</li>
          <li>Fill in the product brief, constraints, and target platform.</li>
          <li>Copy the generated prompt into Codex or Claude, then build with the chosen `DESIGN.md`.</li>
        </ol>
      </aside>
    </section>

    <section class="studio" id="studio">
      <div class="studio-header">
        <div>
          <span class="eyebrow">Selection Studio</span>
          <h2 style="margin-top:14px; font-size:42px; line-height:0.98;">Visual choice and prompt generation live in one place.</h2>
          <p class="studio-copy">
            Pick a card below, review its exact `DESIGN.md` path, then generate a prompt that tells the agent to apply the design system faithfully without copying the source site's content blindly.
          </p>
        </div>
      </div>

      <div class="studio-layout">
        <aside class="selected-panel">
          <div class="selected-placeholder" id="selectedPlaceholder">
            Select a design card below to inspect its path, previews, and ready-to-use prompt context.
          </div>

          <div class="selected-card" id="selectedCard">
            <div class="selected-top">
              <div>
                <h3 id="selectedName"></h3>
                <div class="selected-subtitle" id="selectedMeta"></div>
              </div>
              <span class="pill" id="selectedCategory"></span>
            </div>
            <p class="selected-summary" id="selectedSummary"></p>
            <div class="selected-swatches" id="selectedSwatches"></div>
            <div class="path-box">
              <span class="path-label">DESIGN.md Path</span>
              <div class="path-value" id="selectedPath"></div>
            </div>
            <div class="selected-actions">
              <a class="action action-secondary" id="selectedDesignLink" href="#" target="_blank" rel="noreferrer">Open DESIGN.md</a>
              <a class="action action-outline" id="selectedPreviewLink" href="#" target="_blank" rel="noreferrer">Open Light Preview</a>
              <a class="action action-outline" id="selectedDarkPreviewLink" href="#" target="_blank" rel="noreferrer">Open Dark Preview</a>
            </div>
          </div>
        </aside>

        <section class="composer-panel">
          <span class="eyebrow">Prompt Composer</span>
          <p class="studio-copy" style="margin-bottom: 18px;">
            The generated prompt tells the agent to read the chosen `DESIGN.md`, keep the product brief intact, and carry over the visual language faithfully.
          </p>

          <div class="segmented" id="agentSegments">
            <button class="segment active" type="button" data-agent="codex">Codex</button>
            <button class="segment" type="button" data-agent="claude">Claude Code</button>
            <button class="segment" type="button" data-agent="generic">Generic Agent</button>
          </div>

          <div class="composer-grid">
            <div class="field">
              <span class="field-label">Task Type</span>
              <select class="select" id="taskType">
                <option value="landing page">Landing page</option>
                <option value="marketing site">Marketing site</option>
                <option value="product dashboard">Product dashboard</option>
                <option value="app shell">App shell</option>
                <option value="design refresh">Design refresh</option>
                <option value="component system">Component system</option>
              </select>
            </div>
            <div class="field">
              <span class="field-label">Surface</span>
              <select class="select" id="surfaceType">
                <option value="responsive desktop and mobile">Responsive desktop and mobile</option>
                <option value="desktop-first web">Desktop-first web</option>
                <option value="mobile-first web">Mobile-first web</option>
                <option value="tablet and desktop">Tablet and desktop</option>
              </select>
            </div>
            <div class="field">
              <span class="field-label">Output Mode</span>
              <select class="select" id="outputMode">
                <option value="build new UI">Build new UI</option>
                <option value="restyle existing UI">Restyle existing UI</option>
                <option value="extend an existing screen">Extend an existing screen</option>
                <option value="turn a wireframe into polished UI">Turn a wireframe into polished UI</option>
              </select>
            </div>
            <div class="field">
              <span class="field-label">Prompt Tone</span>
              <select class="select" id="promptTone">
                <option value="faithful">Faithful to the source design</option>
                <option value="inspired">Inspired by the source design</option>
                <option value="blended">Blend with the current product</option>
              </select>
            </div>
            <div class="field field-wide">
              <span class="field-label">Product Brief</span>
              <textarea class="textarea" id="briefInput" placeholder="Describe the page or app you want to build, who it is for, and what the core outcome should be."></textarea>
            </div>
            <div class="field field-wide">
              <span class="field-label">Non-negotiables</span>
              <textarea class="textarea" id="constraintsInput" placeholder="List the pieces that must survive the styling pass: IA, conversion goals, brand constraints, accessibility, existing components, shipping constraints, and so on."></textarea>
            </div>
            <div class="field field-wide">
              <span class="field-label">Extra Notes</span>
              <textarea class="textarea" id="notesInput" placeholder="Optional notes: components to emphasize, pages to skip, motion constraints, dark mode preference, codebase context, or handoff expectations."></textarea>
            </div>
            <div class="field field-wide">
              <span class="field-label">Generated Prompt</span>
              <textarea class="textarea prompt-output" id="promptOutput" readonly>Select a design first, then the prompt will appear here.</textarea>
            </div>
          </div>

          <div class="builder-actions">
            <button class="action action-primary" type="button" id="copyPromptButton">Copy Prompt</button>
            <button class="action action-copy" type="button" id="copyPathButton">Copy DESIGN.md Path</button>
            <button class="action action-outline" type="button" id="resetBuilderButton">Reset Brief Fields</button>
          </div>
          <div class="status" id="copyStatus">Choose a design to activate the composer.</div>
        </section>
      </div>
    </section>

    <section class="controls">
      <div class="search-row">
        <input id="search" class="search" type="search" placeholder="Search by site, category, or style words like editorial, gradient, fintech, minimal, cinematic..." />
        <div id="results" class="results">{count} designs</div>
      </div>
      <div class="filters">
        <button class="filter-chip active" type="button" data-category="__all__">All</button>
        {category_buttons}
      </div>
    </section>

    <section id="grid" class="grid">
      {cards}
    </section>
    <div id="empty" class="empty">No designs matched the current filters. Try another keyword or reset to All.</div>
  </div>

  <script>
    const RAW_DESIGN_DATA = {payload_json};

    function fileUrlToLocalPath(url) {{
      const decoded = decodeURIComponent(url.pathname);
      if (/^\\/[A-Za-z]:\\//.test(decoded)) {{
        return decoded.slice(1).replaceAll("/", "\\\\");
      }}
      return decoded;
    }}

    function localPathFor(relativePath) {{
      const url = new URL(relativePath, window.location.href);
      if (url.protocol === "file:") {{
        return fileUrlToLocalPath(url);
      }}
      return url.href;
    }}

    const SKILL_ROOT = localPathFor("../");
    const DESIGN_DATA = RAW_DESIGN_DATA.map((entry) => ({{
      ...entry,
      design_md_abs: localPathFor(entry.design_md),
      preview_abs: localPathFor(entry.preview),
      preview_dark_abs: entry.preview_dark ? localPathFor(entry.preview_dark) : null,
    }}));
    const designMap = new Map(DESIGN_DATA.map((entry) => [entry.slug, entry]));

    const searchInput = document.getElementById("search");
    const resultLabel = document.getElementById("results");
    const cards = Array.from(document.querySelectorAll(".design-card"));
    const chips = Array.from(document.querySelectorAll(".filter-chip"));
    const empty = document.getElementById("empty");
    const chooseButtons = Array.from(document.querySelectorAll('[data-action="choose"]'));

    const selectedPlaceholder = document.getElementById("selectedPlaceholder");
    const selectedCard = document.getElementById("selectedCard");
    const selectedName = document.getElementById("selectedName");
    const selectedMeta = document.getElementById("selectedMeta");
    const selectedCategory = document.getElementById("selectedCategory");
    const selectedSummary = document.getElementById("selectedSummary");
    const selectedSwatches = document.getElementById("selectedSwatches");
    const selectedPath = document.getElementById("selectedPath");
    const selectedDesignLink = document.getElementById("selectedDesignLink");
    const selectedPreviewLink = document.getElementById("selectedPreviewLink");
    const selectedDarkPreviewLink = document.getElementById("selectedDarkPreviewLink");

    const taskType = document.getElementById("taskType");
    const surfaceType = document.getElementById("surfaceType");
    const outputMode = document.getElementById("outputMode");
    const promptTone = document.getElementById("promptTone");
    const briefInput = document.getElementById("briefInput");
    const constraintsInput = document.getElementById("constraintsInput");
    const notesInput = document.getElementById("notesInput");
    const promptOutput = document.getElementById("promptOutput");
    const copyPromptButton = document.getElementById("copyPromptButton");
    const copyPathButton = document.getElementById("copyPathButton");
    const resetBuilderButton = document.getElementById("resetBuilderButton");
    const copyStatus = document.getElementById("copyStatus");
    const agentSegments = Array.from(document.querySelectorAll(".segment"));

    let activeCategory = "__all__";
    let activeAgent = "codex";
    let selectedSlug = null;

    function escapeHtml(value) {{
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function setStatus(message) {{
      copyStatus.textContent = message;
    }}

    function selectedDesign() {{
      return selectedSlug ? designMap.get(selectedSlug) : null;
    }}

    function placeholder(text, fallback) {{
      const value = text.trim();
      return value ? value : fallback;
    }}

    function promptLead(agent) {{
      if (agent === "codex") {{
        return [
          "Use $awesome-design as the design-selection workflow for this frontend task.",
          "The skill root is: " + SKILL_ROOT,
        ];
      }}
      if (agent === "claude") {{
        return [
          "Use $awesome-design to guide the visual direction for this frontend task.",
          "The skill root is: " + SKILL_ROOT,
        ];
      }}
      return [
        "Use the selected DESIGN.md as the design system reference for this frontend task.",
        "The local awesome-design library lives at: " + SKILL_ROOT,
      ];
    }}

    function buildPrompt() {{
      const design = selectedDesign();
      if (!design) {{
        return "Select a design card first, then the prompt composer will generate a ready-to-send prompt here.";
      }}

      const lines = [
        ...promptLead(activeAgent),
        "",
        "Selected design:",
        "- Design system: " + design.display_name,
        "- Category: " + design.category,
        "- DESIGN.md: " + design.design_md_abs,
        "- Light preview: " + design.preview_abs,
        design.preview_dark_abs ? "- Dark preview: " + design.preview_dark_abs : "- Dark preview: not available",
        "",
        "Task framing:",
        "- Task type: " + taskType.value,
        "- Surface: " + surfaceType.value,
        "- Output mode: " + outputMode.value,
        "- Styling intent: " + promptTone.value,
        "",
        "Execution requirements:",
        "1. Read the DESIGN.md before making layout or styling decisions.",
        "2. Carry over the selected system's typography, color roles, spacing, surfaces, buttons, cards, and visual rhythm.",
        "3. Preserve the product brief and UX goals instead of copying the source site's content or information architecture blindly.",
        "4. Keep the result responsive and production-credible.",
        "5. If you deviate from the source design, keep the spirit intact and explain the tradeoff briefly.",
        "",
        "Product brief:",
        placeholder(
          briefInput.value,
          "Describe the product, user, primary flow, and what the final page or screen must accomplish."
        ),
        "",
        "Non-negotiables:",
        placeholder(
          constraintsInput.value,
          "List the IA, conversion goals, accessibility rules, component constraints, existing brand limits, or technical boundaries that must not be broken."
        ),
        "",
        "Extra notes:",
        placeholder(
          notesInput.value,
          "Optional notes about emphasis, motion, dark mode preference, codebase context, or delivery expectations."
        ),
      ];

      return lines.join("\\n");
    }}

    function renderSelectedState() {{
      const design = selectedDesign();
      if (!design) {{
        selectedPlaceholder.style.display = "grid";
        selectedCard.classList.remove("visible");
        promptOutput.value = buildPrompt();
        copyPromptButton.disabled = true;
        copyPathButton.disabled = true;
        setStatus("Choose a design to activate the composer.");
        return;
      }}

      selectedPlaceholder.style.display = "none";
      selectedCard.classList.add("visible");
      selectedName.textContent = design.display_name;
      selectedMeta.textContent = design.title + " · " + design.slug;
      selectedCategory.textContent = design.category;
      selectedSummary.textContent = design.summary;
      selectedPath.textContent = design.design_md_abs;
      selectedDesignLink.href = design.design_md;
      selectedPreviewLink.href = design.preview;
      selectedDarkPreviewLink.href = design.preview_dark || "#";
      selectedDarkPreviewLink.style.display = design.preview_dark ? "inline-flex" : "none";
      selectedSwatches.innerHTML = design.colors
        .slice(0, 6)
        .map((color) => '<span class="swatch" style="background:' + escapeHtml(color) + '" title="' + escapeHtml(color) + '"></span>')
        .join("");

      promptOutput.value = buildPrompt();
      copyPromptButton.disabled = false;
      copyPathButton.disabled = false;
      setStatus("Selected " + design.display_name + ". Adjust the brief fields and copy the prompt when ready.");
    }}

    function updateCards() {{
      for (const card of cards) {{
        card.classList.toggle("selected", card.dataset.slug === selectedSlug);
      }}
    }}

    function updateFilter() {{
      const query = searchInput.value.trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {{
        const categoryMatch = activeCategory === "__all__" || card.dataset.category === activeCategory;
        const searchMatch = !query || card.dataset.search.includes(query);
        const show = categoryMatch && searchMatch;
        card.style.display = show ? "" : "none";
        if (show) visible += 1;
      }}
      resultLabel.textContent = visible + " design" + (visible === 1 ? "" : "s");
      empty.style.display = visible === 0 ? "block" : "none";
    }}

    async function copyText(text) {{
      try {{
        await navigator.clipboard.writeText(text);
        return true;
      }} catch (error) {{
        promptOutput.focus();
        promptOutput.select();
        return document.execCommand("copy");
      }}
    }}

    function selectDesign(slug) {{
      selectedSlug = slug;
      updateCards();
      renderSelectedState();
      if (window.innerWidth < 980) {{
        document.getElementById("studio").scrollIntoView({{ behavior: "smooth", block: "start" }});
      }}
    }}

    for (const button of chooseButtons) {{
      button.addEventListener("click", () => selectDesign(button.dataset.slug));
    }}

    for (const chip of chips) {{
      chip.addEventListener("click", () => {{
        activeCategory = chip.dataset.category;
        for (const other of chips) {{
          other.classList.remove("active");
        }}
        chip.classList.add("active");
        updateFilter();
      }});
    }}

    for (const segment of agentSegments) {{
      segment.addEventListener("click", () => {{
        activeAgent = segment.dataset.agent;
        for (const other of agentSegments) {{
          other.classList.remove("active");
        }}
        segment.classList.add("active");
        promptOutput.value = buildPrompt();
        const design = selectedDesign();
        if (design) {{
          setStatus("Prompt updated for " + segment.textContent + ".");
        }}
      }});
    }}

    for (const field of [taskType, surfaceType, outputMode, promptTone, briefInput, constraintsInput, notesInput]) {{
      field.addEventListener("input", () => {{
        promptOutput.value = buildPrompt();
      }});
      field.addEventListener("change", () => {{
        promptOutput.value = buildPrompt();
      }});
    }}

    copyPromptButton.addEventListener("click", async () => {{
      const design = selectedDesign();
      if (!design) {{
        setStatus("Select a design before copying a prompt.");
        return;
      }}
      const ok = await copyText(promptOutput.value);
      const agentLabel = activeAgent === "claude" ? "Claude Code" : (activeAgent === "generic" ? "generic agent" : "Codex");
      setStatus(ok ? ("Copied a " + agentLabel + " prompt for " + design.display_name + ".") : "Copy failed. The prompt is selected; copy it manually.");
    }});

    copyPathButton.addEventListener("click", async () => {{
      const design = selectedDesign();
      if (!design) {{
        setStatus("Select a design before copying the DESIGN.md path.");
        return;
      }}
      const ok = await copyText(design.design_md_abs);
      setStatus(ok ? ("Copied DESIGN.md path for " + design.display_name + ".") : "Copy failed. The path is visible in the selected design panel.");
    }});

    resetBuilderButton.addEventListener("click", () => {{
      briefInput.value = "";
      constraintsInput.value = "";
      notesInput.value = "";
      taskType.value = "landing page";
      surfaceType.value = "responsive desktop and mobile";
      outputMode.value = "build new UI";
      promptTone.value = "faithful";
      promptOutput.value = buildPrompt();
      setStatus("Brief fields reset. The selected design stayed in place.");
    }});

    searchInput.addEventListener("input", updateFilter);

    updateFilter();
    renderSelectedState();
  </script>
</body>
</html>
"""


def write_outputs(entries: list[DesignEntry], output_dir: Path, skill_root: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "designs.json"
    html_path = output_dir / "index.html"

    json_path.write_text(
        json.dumps(catalog_payload(entries), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_html(entries, skill_root), encoding="utf-8")
    return html_path, json_path


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    open_after = "--open" in args

    skill_root = Path(__file__).resolve().parent.parent
    output_dir = skill_root / "preview-library"
    entries = collect_designs(skill_root)
    if not entries:
        print("No previewable designs found.")
        return 1

    html_path, json_path = write_outputs(entries, output_dir, skill_root)
    print(f"Generated preview library: {html_path}")
    print(f"Generated catalog data:  {json_path}")
    print(f"Indexed designs:         {len(entries)}")

    if open_after:
        webbrowser.open(html_path.resolve().as_uri())
        print("Opened preview library in the default browser.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
