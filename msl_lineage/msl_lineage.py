#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""
MSL Lineage Visualizer — interactief data-lineage diagram vanuit een IBM MSL bestand.

Gebruik:
  python3 msl_lineage.py              # genereert <bestandsnaam>_Lineage.html

Vereisten:
  msl_convert.py moet in dezelfde map staan (wordt geïmporteerd voor parsing).
  Één .msl bestand in de map.

Output:
  <bestandsnaam>_Lineage.html — standalone HTML, geen externe dependencies.
"""

import sys
import json
import logging
from pathlib import Path

# Importeer parse-logica uit msl_convert
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
OUTPUT_DIR = ROOT_DIR / 'output'
sys.modules.pop('msl_convert', None)
sys.path.insert(0, str(ROOT_DIR / 'msl_convert'))

try:
    from msl_convert import (
        find_msl_file, validate_msl, parse_msl,
        LOG_FILE,
    )
    from xml.etree import ElementTree as ET
except ImportError as e:
    print(f"Fout: msl_convert.py niet gevonden in {ROOT_DIR / 'msl_convert'}\n{e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging (zelfde bestand als msl_convert)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data-voorbereiding voor de visualisatie
# ---------------------------------------------------------------------------
def build_lineage_data(data: dict) -> dict:
    """
    Bouw een genormaliseerde datastructuur voor de lineage HTML.
    Gebruikt volledige bronnamen (geen aliases) — leesbaar in het diagram.

    Bronnen krijgen een 'primary' vlag:
      primary = levert directe/concat/constant attribuutwaarden (>= 2x)
      secondary = verschijnt alleen als join/lookup-partner
    """
    sources_raw = data['all_sources']

    # Per bron: naar welke doelen, hoeveel attributen
    src_info: dict[str, dict] = {}
    for s in sources_raw:
        src_info[s] = {
            'name':        s,
            'targets':     [],
            'total_attrs': 0,
        }

    # Per doeltabel: edges en joins
    targets_out = []
    for m in data['target_mappings']:
        by_src: dict[str, dict] = {}
        for a in m['attributes']:
            for _res, tbl, field in a['inputs']:
                if tbl not in by_src:
                    by_src[tbl] = {'count': 0, 'types': set(), 'attrs': []}
                by_src[tbl]['count'] += 1
                by_src[tbl]['types'].add(a['type'])
                notes = a['notes']
                by_src[tbl]['attrs'].append({
                    'target': a['target'],
                    'field':  field,
                    'type':   a['type'],
                    'notes':  notes[:200] + '…' if len(notes) > 200 else notes,
                })

        edges = []
        for src, info in by_src.items():
            edges.append({
                'src_id':   src,          # volledige naam, geen alias
                'count':    info['count'],
                'types':    sorted(info['types']),
                'attrs':    info['attrs'],
            })
            if src in src_info:
                src_info[src]['targets'].append({
                    'table': m['target_table'],
                    'count': info['count'],
                    'types': sorted(info['types']),
                })
                src_info[src]['total_attrs'] += info['count']

        joins_out = []
        for j in m['joins']:
            joins_out.append({
                'sources': j['sources'],   # ook volledige namen
                'fields':  j['fields'],
            })

        targets_out.append({
            'id':     m['target_table'],
            'filter': m['filter'],
            'edges':  edges,
            'joins':  joins_out,
        })

    # Bron-objecten voor JS
    sources_out = []
    for s in sources_raw:
        info = src_info[s]
        # primary = levert echte waarden (direct/concat/constant), minstens 2x
        primary_count = 0
        for m in data['target_mappings']:
            for a in m['attributes']:
                if s in [i[1] for i in a['inputs']] and a['type'] in ('direct', 'concat', 'constant'):
                    primary_count += 1
        sources_out.append({
            'id':       s,              # volledige naam als identifier én label
            'primary':  primary_count >= 2,
            'n_targets': len(info['targets']),
            'n_attrs':   info['total_attrs'],
        })

    return {
        'source_location': data['source_location'],
        'target_location': data['target_location'],
        'sources':  sources_out,
        'targets':  targets_out,
    }


# ---------------------------------------------------------------------------
# HTML renderen
# ---------------------------------------------------------------------------
LINEAGE_HTML = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<title>{title} — Lineage</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#eef2f7; font-family:Arial,sans-serif; color:#1a2a3a; overflow:hidden; }}

/* ── Toolbar ─────────────────────────────────────────── */
#toolbar {{
  position:fixed; top:0; left:0; right:0; height:52px; z-index:200;
  background:#005b9a; display:flex; align-items:center; gap:10px; padding:0 16px;
  box-shadow:0 2px 8px rgba(0,0,0,0.2);
}}
#uwv-logo {{
  font-size:18px; font-weight:700; background:#fff; color:#005b9a;
  padding:2px 9px; border-radius:3px; line-height:1.4; flex-shrink:0;
}}
#toolbar h1 {{ font-size:13px; color:#cce0f5; flex:1; font-weight:400; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
#toolbar h1 strong {{ color:#fff; font-weight:700; }}

/* Filter-chips */
#filters {{ display:flex; gap:6px; align-items:center; flex-shrink:0; }}
.chip {{
  display:flex; align-items:center; gap:5px; padding:4px 9px;
  border-radius:12px; font-size:11px; font-weight:600; cursor:pointer;
  border:1.5px solid transparent; transition:opacity .15s;
}}
.chip input {{ cursor:pointer; }}
.chip-direct   {{ background:#1a6fa8; color:#fff; border-color:#1a6fa8; }}
.chip-concat   {{ background:#e07b00; color:#fff; border-color:#e07b00; }}
.chip-lookup   {{ background:#6a3fa0; color:#fff; border-color:#6a3fa0; }}
.chip-join     {{ background:#1a8a50; color:#fff; border-color:#1a8a50; }}
.chip-constant {{ background:#888; color:#fff; border-color:#888; }}
.chip.off      {{ opacity:0.35; }}
.sep {{ width:1px; height:28px; background:rgba(255,255,255,0.2); flex-shrink:0; }}

.btn {{
  padding:5px 11px; border-radius:4px; border:1.5px solid rgba(255,255,255,0.35);
  background:rgba(255,255,255,0.1); color:#fff; cursor:pointer;
  font-size:12px; font-family:inherit; font-weight:600; white-space:nowrap; flex-shrink:0;
}}
.btn:hover {{ background:rgba(255,255,255,0.22); }}
#search {{
  padding:4px 9px; border-radius:4px; border:1.5px solid rgba(255,255,255,0.35);
  background:rgba(255,255,255,0.12); color:#fff; font-size:12px; width:140px; outline:none;
}}
#search::placeholder {{ color:rgba(255,255,255,0.45); }}
#search:focus {{ background:rgba(255,255,255,0.2); }}

/* ── Canvas ───────────────────────────────────────────── */
#canvas-wrap {{
  position:fixed; top:52px; left:0; right:0; bottom:0; overflow:hidden;
  background:#eef2f7;
  background-image:radial-gradient(circle,#c5d5e5 1px,transparent 1px);
  background-size:22px 22px;
  cursor:grab;
}}
#canvas-wrap.panning {{ cursor:grabbing; }}
#canvas {{ position:absolute; top:0; left:0; transform-origin:0 0; }}
svg#lines {{ position:absolute; top:0; left:0; pointer-events:none; overflow:visible; }}

/* ── Kolom-labels ─────────────────────────────────────── */
.col-label {{
  position:absolute; font-size:11px; font-weight:700; color:#5580a0;
  text-transform:uppercase; letter-spacing:1px; pointer-events:none;
  top:-28px; white-space:nowrap;
}}

/* ── Kaarten ──────────────────────────────────────────── */
.card {{
  position:absolute; border-radius:6px; user-select:none;
  box-shadow:0 2px 8px rgba(0,91,154,0.13);
  transition:box-shadow .15s, opacity .2s;
  min-width:200px; max-width:240px;
}}
.card.src   {{ border:2px solid #2a7ab8; }}
.card.tgt   {{ border:2px solid #005b9a; }}
.card.sec   {{ border:2px solid #8aade0; }}   /* secondary bron */
.card.dimmed {{ opacity:0.18; }}
.card.highlighted {{ box-shadow:0 0 0 3px #f5a623, 0 4px 18px rgba(0,0,0,0.18); }}
.card.search-match {{ box-shadow:0 0 0 3px #2ecc71, 0 4px 18px rgba(0,0,0,0.18); }}
.card:hover {{ box-shadow:0 4px 18px rgba(0,91,154,0.28); }}

.card-header {{
  padding:7px 10px; border-radius:4px 4px 0 0; cursor:pointer;
}}
.card.src .card-header {{ background:#2a7ab8; }}
.card.tgt .card-header {{ background:#005b9a; }}
.card.sec .card-header {{ background:#6a9fc8; }}
.card.highlighted .card-header {{ background:#c05000; }}

.card-name  {{ font-size:11px; font-weight:700; color:#fff; }}
.card-sub   {{ font-size:9px; color:rgba(255,255,255,0.7); margin-top:2px; }}
.card-badge {{
  display:inline-block; font-size:9px; font-weight:700;
  padding:1px 5px; border-radius:8px; margin-left:6px;
  background:rgba(255,255,255,0.22); color:#fff;
}}

/* Attribuutlijst in doelkaart */
.card-attrs {{ border-top:1px solid rgba(0,0,0,0.06); }}
.attr-row {{
  display:flex; align-items:center; padding:3px 10px; gap:4px;
  font-size:9.5px; border-bottom:1px solid #e8eff6; cursor:default;
  transition:background .1s;
}}
.attr-row:last-child {{ border-bottom:none; }}
.attr-row:hover {{ background:#f0f7ff; }}
.attr-row.active {{ background:#fff3d4; }}
.attr-name {{ flex:1; color:#223344; }}
.attr-dot {{
  width:8px; height:8px; border-radius:50%; flex-shrink:0;
}}
.dot-direct   {{ background:#1a6fa8; }}
.dot-concat   {{ background:#e07b00; }}
.dot-lookup   {{ background:#6a3fa0; }}
.dot-join     {{ background:#1a8a50; }}
.dot-constant {{ background:#888; }}
.attr-src {{ font-size:8.5px; color:#7a99bb; white-space:nowrap; max-width:80px; overflow:hidden; text-overflow:ellipsis; }}

.card-toggle {{
  display:block; text-align:center; padding:4px; font-size:10px;
  font-weight:600; color:#005b9a; cursor:pointer;
  background:#f5f9fd; border-top:1px solid #d0dce8; border-radius:0 0 4px 4px;
}}
.card-toggle:hover {{ background:#e4f0fb; }}

/* ── Detail panel (rechts) ────────────────────────────── */
#detail {{
  position:fixed; top:52px; right:0; bottom:0; width:340px;
  background:#fff; border-left:2px solid #c0d8ee;
  box-shadow:-4px 0 18px rgba(0,0,0,0.1);
  transform:translateX(100%); transition:transform .25s ease;
  z-index:150; display:flex; flex-direction:column; overflow:hidden;
}}
#detail.open {{ transform:translateX(0); }}
#detail-header {{
  background:#005b9a; padding:12px 14px; flex-shrink:0;
  display:flex; align-items:flex-start; gap:8px;
}}
#detail-title {{ font-size:12px; font-weight:700; color:#fff; flex:1; }}
#detail-sub {{ font-size:10px; color:#aac8e8; margin-top:2px; }}
#detail-close {{
  color:rgba(255,255,255,0.7); cursor:pointer; font-size:18px;
  line-height:1; flex-shrink:0; padding:0 2px;
}}
#detail-close:hover {{ color:#fff; }}
#detail-body {{ flex:1; overflow-y:auto; padding:12px; }}
.detail-section {{ margin-bottom:14px; }}
.detail-section h4 {{
  font-size:10px; font-weight:700; color:#005b9a;
  text-transform:uppercase; letter-spacing:.5px;
  border-bottom:1px solid #dde8f4; padding-bottom:4px; margin-bottom:6px;
}}
.detail-row {{
  display:flex; gap:6px; margin-bottom:5px; font-size:11px; align-items:flex-start;
}}
.detail-row .lbl {{
  font-weight:700; color:#334455; flex-shrink:0; min-width:70px;
}}
.detail-row .val {{ color:#445566; }}
.detail-note {{
  background:#f8f4e8; border-left:3px solid #e07b00;
  padding:5px 8px; font-size:10.5px; color:#553300;
  border-radius:0 3px 3px 0; line-height:1.5; margin-top:4px;
}}
.detail-tag {{
  display:inline-block; font-size:9px; font-weight:700; padding:1px 6px;
  border-radius:8px; color:#fff; margin-right:3px;
}}
.detail-filter-note {{
  background:#eef6ff; border-left:3px solid #2a7ab8;
  padding:6px 8px; font-size:10.5px; color:#1a3a5a; line-height:1.5;
  border-radius:0 3px 3px 0; margin-bottom:10px;
}}
.detail-table {{ width:100%; border-collapse:collapse; font-size:10.5px; }}
.detail-table th {{
  background:#f0f7ff; color:#005b9a; font-weight:700;
  padding:4px 7px; text-align:left; border-bottom:1px solid #d0dce8;
}}
.detail-table td {{ padding:4px 7px; border-bottom:1px solid #eef2f7; vertical-align:top; }}
.detail-table tr:last-child td {{ border-bottom:none; }}
.detail-table tr:hover td {{ background:#f8fbff; }}

/* ── Tooltip ──────────────────────────────────────────── */
#tooltip {{
  position:fixed; background:#1c2c3c; border:1px solid #005b9a;
  padding:7px 11px; border-radius:4px; font-size:11px; color:#d8eaf8;
  max-width:280px; pointer-events:none; display:none; z-index:1000;
  line-height:1.5; box-shadow:0 4px 12px rgba(0,0,0,0.25);
}}

/* ── Info-balk ────────────────────────────────────────── */
#info-panel {{
  position:fixed; bottom:12px; left:50%; transform:translateX(-50%);
  background:rgba(0,40,80,0.82); backdrop-filter:blur(4px);
  border-radius:5px; padding:5px 14px; font-size:11px; color:#cce4f8;
  z-index:100; white-space:nowrap; pointer-events:none;
}}
</style>
</head>
<body>

<div id="toolbar">
  <div id="uwv-logo">UWV</div>
  <h1><strong>{title}</strong> — Data Lineage</h1>
  <div id="filters">
    <div class="chip chip-direct"   onclick="toggleType('direct')"  ><input type="checkbox" checked id="chk-direct"  > direct</div>
    <div class="chip chip-concat"   onclick="toggleType('concat')"  ><input type="checkbox" checked id="chk-concat"  > concat</div>
    <div class="chip chip-lookup"   onclick="toggleType('lookup')"  ><input type="checkbox" checked id="chk-lookup"  > lookup</div>
    <div class="chip chip-join"     onclick="toggleType('join')"    ><input type="checkbox" checked id="chk-join"    > join</div>
    <div class="chip chip-constant" onclick="toggleType('constant')"><input type="checkbox" checked id="chk-constant"> constant</div>
  </div>
  <div class="sep"></div>
  <input id="search" type="text" placeholder="🔍 Zoek tabel…" oninput="doSearch(this.value)">
  <button class="btn" onclick="resetHighlight()">✕ Reset</button>
  <button class="btn" onclick="fitView()">⊡ Fit</button>
</div>

<div id="canvas-wrap">
  <div id="canvas">
    <svg id="lines"></svg>
  </div>
</div>

<div id="detail">
  <div id="detail-header">
    <div style="flex:1">
      <div id="detail-title">—</div>
      <div id="detail-sub"></div>
    </div>
    <div id="detail-close" onclick="closeDetail()">✕</div>
  </div>
  <div id="detail-body"></div>
</div>

<div id="tooltip"></div>
<div id="info-panel">Klik op een kaart voor details • Hover over lijn voor attribuutinfo • Scroll = zoom • Sleep canvas = pan</div>

<script>
// ── Data ────────────────────────────────────────────────────────────────────
const SOURCES = {sources_json};
const TARGETS = {targets_json};
const META    = {meta_json};

// Kleur per type
const TYPE_COLOR = {{
  direct:   '#1a6fa8',
  concat:   '#e07b00',
  lookup:   '#6a3fa0',
  join:     '#1a8a50',
  constant: '#888888',
}};

// ── State ───────────────────────────────────────────────────────────────────
let activeTypes = new Set(['direct','concat','lookup','join','constant']);
let focusId     = null;   // gehighlight kaart-id
let off  = {{x:60, y:60}}, sc = 0.82;
let panning = false, ps = {{x:0,y:0}};

const wrap   = document.getElementById('canvas-wrap');
const canvas = document.getElementById('canvas');
const svg    = document.getElementById('lines');
const tip    = document.getElementById('tooltip');

// ── Layout berekenen ─────────────────────────────────────────────────────────
// Bronnen links, doelen rechts. Y-positie op basis van aantal verbindingen.
const COL_SRC_X  = 0;
const COL_TGT_X  = 420;
const CARD_W     = 230;
const ROW_H_SRC  = 72;
const ROW_H_TGT  = 80;

// Sorteer bronnen: primair eerst, dan op n_targets desc
const srcsSorted = [...SOURCES].sort((a,b) => {{
  if (a.primary !== b.primary) return b.primary - a.primary;
  return b.n_targets - a.n_targets;
}});

// Posities bronnen
const srcPos = {{}};
srcsSorted.forEach((s, i) => {{
  srcPos[s.id] = {{ x: COL_SRC_X, y: i * ROW_H_SRC }};
}});

// Posities doelen
const tgtPos = {{}};
TARGETS.forEach((t, i) => {{
  tgtPos[t.id] = {{ x: COL_TGT_X, y: i * ROW_H_TGT }};
}});

// ── DOM-elementen aanmaken ────────────────────────────────────────────────────
function makeSrcCard(s) {{
  const el = document.createElement('div');
  el.className = 'card ' + (s.primary ? 'src' : 'sec');
  el.id = 'card_' + cssId(s.id);
  el.style.left = srcPos[s.id].x + 'px';
  el.style.top  = srcPos[s.id].y + 'px';
  el.style.width = CARD_W + 'px';

  const hdr = document.createElement('div');
  hdr.className = 'card-header';
  hdr.innerHTML = `<div class="card-name">${{s.id}}</div>`
    + `<div class="card-sub">`
    + `<span class="card-badge">${{s.n_attrs}} attrs → ${{s.n_targets}} tabel(len)</span>`
    + (s.primary ? '' : ' <em>secondary</em>')
    + `</div>`;
  hdr.addEventListener('click', () => setFocus(s.id, 'src'));
  hdr.addEventListener('mousemove', ev => showTip(ev,
    `${{s.id}}\n${{s.primary ? 'Primaire bron' : 'Secundaire bron (join/lookup)'}}`
    + ` — ${{s.n_attrs}} attribuutmappings naar ${{s.n_targets}} doeltabel(len)`));
  hdr.addEventListener('mouseleave', hideTip);
  el.appendChild(hdr);
  canvas.appendChild(el);
}}

function makeTgtCard(t) {{
  const el = document.createElement('div');
  el.className = 'card tgt';
  el.id = 'card_' + cssId(t.id);
  el.style.left = tgtPos[t.id].x + 'px';
  el.style.top  = tgtPos[t.id].y + 'px';
  el.style.width = CARD_W + 'px';

  const totalAttrs = t.edges.reduce((s,e) => s+e.count, 0);

  // Header
  const hdr = document.createElement('div');
  hdr.className = 'card-header';
  hdr.innerHTML = `<div class="card-name">${{t.id}}</div>`
    + `<div class="card-sub"><span class="card-badge">${{totalAttrs}} attrs</span>`
    + ` ${{t.edges.length}} bron(nen)</div>`;
  hdr.addEventListener('click', () => openDetail(t));
  hdr.addEventListener('mousemove', ev => {{
    const srcNames = t.edges.map(e=>e.src_id).join(', ');
    showTip(ev, `${{t.id}}\n${{totalAttrs}} attributen uit: ${{srcNames}}`);
  }});  hdr.addEventListener('mouseleave', hideTip);
  el.appendChild(hdr);

  // Attribuutlijst (ingeklapt)
  const attrWrap = document.createElement('div');
  attrWrap.className = 'card-attrs';
  attrWrap.style.display = 'none';

  // Verzamel alle attrs over alle edges
  const allAttrs = [];
  t.edges.forEach(e => {{
    e.attrs.forEach(a => allAttrs.push({{...a, src_id: e.src_id}}));
  }});
  allAttrs.sort((a,b) => a.target.localeCompare(b.target));

  allAttrs.forEach(a => {{
    const row = document.createElement('div');
    row.className = 'attr-row';
    row.dataset.type = a.type;
    row.dataset.src  = a.src_id;
    const color = TYPE_COLOR[a.type] || '#888';
    row.innerHTML = `<div class="attr-dot" style="background:${{color}}"></div>`
      + `<div class="attr-name">${{a.target}}</div>`
      + `<div class="attr-src">${{a.src_id}}.`
      + `<span style="color:#334">${{a.field}}</span></div>`;
    if (a.notes) {{
      row.addEventListener('mousemove', ev => showTip(ev, a.notes));
      row.addEventListener('mouseleave', hideTip);
    }}
    attrWrap.appendChild(row);
  }});
  el.appendChild(attrWrap);

  const tog = document.createElement('div');
  tog.className = 'card-toggle';
  tog.textContent = '▾ attributen tonen';
  tog.addEventListener('click', () => {{
    const open = attrWrap.style.display !== 'none';
    attrWrap.style.display = open ? 'none' : 'block';
    tog.textContent = open ? '▾ attributen tonen' : '▴ verbergen';
    setTimeout(draw, 60);
  }});
  el.appendChild(tog);
  canvas.appendChild(el);
}}

function cssId(id) {{
  return id.replace(/[^a-zA-Z0-9]/g, '_');
}}

// ── SVG verbindingslijnen ─────────────────────────────────────────────────────
function getCardMidRight(id) {{
  const el = document.getElementById('card_' + cssId(id));
  if (!el) return null;
  const pos = (srcPos[id] || tgtPos[id]);
  return {{ x: pos.x + el.offsetWidth, y: pos.y + el.offsetHeight/2 }};
}}
function getCardMidLeft(id) {{
  const el = document.getElementById('card_' + cssId(id));
  if (!el) return null;
  const pos = tgtPos[id];
  return {{ x: pos.x, y: pos.y + el.offsetHeight/2 }};
}}

let lineNodes = {{}};  // key → SVG path element

function draw() {{
  // SVG afmeting
  const mw = COL_TGT_X + CARD_W + 200;
  const mh = Math.max(
    srcsSorted.length * ROW_H_SRC,
    TARGETS.length * ROW_H_TGT
  ) + 200;
  svg.setAttribute('width', mw);
  svg.setAttribute('height', mh);

  // Verwijder alle oude lijnen
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  lineNodes = {{}};

  TARGETS.forEach(t => {{
    t.edges.forEach(e => {{
      // Filter op actieve types
      const visibleTypes = e.types.filter(ty => activeTypes.has(ty));
      if (!visibleTypes.length) return;

      const p1 = getCardMidRight(e.src_id);
      const p2 = getCardMidLeft(t.id);
      if (!p1 || !p2) return;

      // Bepaal kleur: prioriteit direct > concat > lookup > join > constant
      const prio = ['direct','concat','lookup','join','constant'];
      const dominantType = prio.find(p => visibleTypes.includes(p)) || visibleTypes[0];
      const col = TYPE_COLOR[dominantType];

      // Dimming
      const isActive = !focusId || focusId === e.src_id || focusId === t.id;
      const opacity = isActive ? 0.65 : 0.07;

      // Lijndikte = log van attrs
      const lw = Math.max(1.2, Math.min(4.5, 1.2 + Math.log(e.count + 1) * 0.8));

      // Bezier
      const cpx = (p1.x + p2.x) / 2;
      const d = `M${{p1.x}},${{p1.y}} C${{cpx}},${{p1.y}} ${{cpx}},${{p2.y}} ${{p2.x}},${{p2.y}}`;

      const path = document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', col);
      path.setAttribute('stroke-width', lw);
      path.setAttribute('opacity', opacity);
      path.style.cursor = 'pointer';

      path.addEventListener('mousemove', ev => {{
        const typeStr = e.types.map(ty =>
          `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${{TYPE_COLOR[ty]}};margin-right:3px"></span>${{ty}}`
        ).join('  ');
        showTipHtml(ev,
          `<strong>${{e.src_id}}</strong> → <strong>${{t.id}}</strong><br>`
          + `${{e.count}} attribuut${{e.count>1?'s':''}} &nbsp; ${{typeStr}}`
        );
      }});
      path.addEventListener('mouseleave', hideTip);

      // Klik: open detail panel gefilterd op deze edge
      path.addEventListener('click', ev => {{
        ev.stopPropagation();
        openDetailFiltered(t, e.src_id);
      }});

      svg.appendChild(path);

      const key = e.src_id + '|' + t.id;
      lineNodes[key] = path;
    }});
  }});
}}

// ── Focus / highlight ─────────────────────────────────────────────────────────
function setFocus(id, kind) {{
  if (focusId === id) {{ focusId = null; }} else {{ focusId = id; }}
  applyDim();
  draw();
}}

function applyDim() {{
  // Bron-kaarten
  SOURCES.forEach(s => {{
    const el = document.getElementById('card_' + cssId(s.id));
    if (!el) return;
    if (!focusId) {{
      el.classList.remove('dimmed','highlighted');
    }} else if (s.id === focusId) {{
      el.classList.add('highlighted'); el.classList.remove('dimmed');
    }} else {{
      // Gerelateerd?
      const related = TARGETS.some(t => t.id === focusId && t.edges.some(e => e.src_id === s.id))
                   || (focusId === s.id);
      el.classList.toggle('dimmed', !related);
      el.classList.toggle('highlighted', false);
    }}
  }});
  // Doel-kaarten
  TARGETS.forEach(t => {{
    const el = document.getElementById('card_' + cssId(t.id));
    if (!el) return;
    if (!focusId) {{
      el.classList.remove('dimmed','highlighted');
    }} else if (t.id === focusId) {{
      el.classList.add('highlighted'); el.classList.remove('dimmed');
    }} else {{
      const related = t.edges.some(e => e.src_id === focusId) || focusId === t.id;
      el.classList.toggle('dimmed', !related);
      el.classList.toggle('highlighted', false);
    }}
  }});
}}

function resetHighlight() {{
  focusId = null;
  applyDim(); draw();
  document.getElementById('search').value = '';
  document.querySelectorAll('.card').forEach(e => e.classList.remove('search-match'));
}}

// ── Filter ────────────────────────────────────────────────────────────────────
function toggleType(type) {{
  if (activeTypes.has(type)) {{ activeTypes.delete(type); }}
  else {{ activeTypes.add(type); }}
  const chip = document.querySelector(`.chip-${{type}}`);
  const chk  = document.getElementById('chk-' + type);
  chip.classList.toggle('off', !activeTypes.has(type));
  if (chk) chk.checked = activeTypes.has(type);

  // Verberg attr-rijen die niet actief zijn
  document.querySelectorAll('.attr-row').forEach(row => {{
    row.style.display = activeTypes.has(row.dataset.type) ? '' : 'none';
  }});
  draw();
}}

// ── Zoeken ────────────────────────────────────────────────────────────────────
function doSearch(q) {{
  q = q.toLowerCase().trim();
  document.querySelectorAll('.card').forEach(el => el.classList.remove('search-match'));
  if (!q) return;
  const allCards = [...SOURCES.map(s=>s.id), ...TARGETS.map(t=>t.id)];
  const matches = allCards.filter(id => id.toLowerCase().includes(q));
  matches.forEach(id => {{
    const el = document.getElementById('card_' + cssId(id));
    if (el) el.classList.add('search-match');
  }});
  if (matches.length) {{
    // Pan naar eerste match
    const firstId = matches[0];
    const pos = srcPos[firstId] || tgtPos[firstId];
    if (pos) {{
      sc = 1.1;
      off.x = wrap.clientWidth/2  - (pos.x + CARD_W/2)*sc;
      off.y = wrap.clientHeight/2 - (pos.y + 40)*sc;
      applyT();
    }}
  }}
}}

// ── Detail panel ──────────────────────────────────────────────────────────────
function openDetail(t) {{
  openDetailFiltered(t, null);
}}

function openDetailFiltered(t, filterSrc) {{
  const panel = document.getElementById('detail');
  document.getElementById('detail-title').textContent = t.id;
  const totalAttrs = t.edges.reduce((s,e)=>s+e.count,0);
  document.getElementById('detail-sub').textContent =
    `${{totalAttrs}} attributen · ${{t.edges.length}} bron(nen)` +
    (filterSrc ? ` · gefilterd op ${{filterSrc}}` : '');

  const body = document.getElementById('detail-body');
  body.innerHTML = '';

  // Filter-tekst
  if (t.filter) {{
    const fn = document.createElement('div');
    fn.className = 'detail-filter-note';
    fn.textContent = t.filter;
    body.appendChild(fn);
  }}

  // Edges (bronnen)
  const edgesToShow = filterSrc ? t.edges.filter(e => e.src_id === filterSrc) : t.edges;
  edgesToShow.forEach(e => {{
    const sec = document.createElement('div');
    sec.className = 'detail-section';

    const h4 = document.createElement('h4');
    h4.innerHTML = `<span class="detail-tag" style="background:${{e.types[0]?TYPE_COLOR[e.types[0]]:'#888'}}">${{e.types.join('/')}}</span> ${{e.src_id}}`;
    sec.appendChild(h4);

    // Tabel met attribuutmappings
    const tbl = document.createElement('table');
    tbl.className = 'detail-table';
    tbl.innerHTML = '<thead><tr><th>Doelattribuut</th><th>Bronveld</th><th>Type</th></tr></thead>';
    const tbody = document.createElement('tbody');

    e.attrs
      .filter(a => activeTypes.has(a.type))
      .forEach(a => {{
        const tr = document.createElement('tr');
        const dot = `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{TYPE_COLOR[a.type]}};margin-right:4px"></span>`;
        tr.innerHTML = `<td>${{a.target}}</td><td style="color:#6680a0">${{a.field}}</td><td>${{dot}}${{a.type}}</td>`;
        if (a.notes) {{
          const noteRow = document.createElement('tr');
          noteRow.innerHTML = `<td colspan="3"><div class="detail-note">${{a.notes}}</div></td>`;
          tr.addEventListener('click', () => noteRow.style.display = noteRow.style.display?'':'none');
          tr.style.cursor = 'pointer';
          tr.title = 'Klik voor notitie';
          tbody.appendChild(tr);
          tbody.appendChild(noteRow);
          noteRow.style.display = 'none';
        }} else {{
          tbody.appendChild(tr);
        }}
      }});

    tbl.appendChild(tbody);
    sec.appendChild(tbl);
    body.appendChild(sec);
  }});

  // Join-condities
  if (t.joins.length) {{
    const sec = document.createElement('div');
    sec.className = 'detail-section';
    const h4 = document.createElement('h4');
    h4.textContent = 'Join-condities';
    sec.appendChild(h4);
    t.joins.forEach(j => {{
      const row = document.createElement('div');
      row.className = 'detail-row';
      row.innerHTML = `<div class="lbl">${{j.sources.join(' = ')}}</div>`
        + `<div class="val">${{j.fields.length ? j.fields.join(', ') : '(zie notities)'}}</div>`;
      sec.appendChild(row);
    }});
    body.appendChild(sec);
  }}

  panel.classList.add('open');

  // Highlight betrokken kaarten
  setFocus(t.id, 'tgt');
}}

function closeDetail() {{
  document.getElementById('detail').classList.remove('open');
  resetHighlight();
}}

// ── Tooltip ───────────────────────────────────────────────────────────────────
function showTip(ev, text) {{
  tip.style.display = 'block';
  tip.innerHTML = text.replace(/\n/g,'<br>');
  positionTip(ev);
}}
function showTipHtml(ev, html) {{
  tip.style.display = 'block';
  tip.innerHTML = html;
  positionTip(ev);
}}
function positionTip(ev) {{
  tip.style.left = Math.min(ev.clientX+14, window.innerWidth-300) + 'px';
  tip.style.top  = Math.min(ev.clientY+14, window.innerHeight-80) + 'px';
}}
function hideTip() {{ tip.style.display = 'none'; }}

// ── Pan & zoom ────────────────────────────────────────────────────────────────
wrap.addEventListener('mousedown', ev => {{
  if (ev.target === wrap || ev.target === canvas || ev.target === svg) {{
    panning = true; wrap.classList.add('panning');
    ps = {{x: ev.clientX - off.x, y: ev.clientY - off.y}};
  }}
}});
document.addEventListener('mousemove', ev => {{
  if (!panning) return;
  off = {{x: ev.clientX - ps.x, y: ev.clientY - ps.y}};
  applyT();
}});
document.addEventListener('mouseup', () => {{ panning = false; wrap.classList.remove('panning'); }});
wrap.addEventListener('wheel', ev => {{
  ev.preventDefault();
  const prev = sc;
  sc = Math.max(0.15, Math.min(3.0, sc * (ev.deltaY > 0 ? 0.9 : 1.11)));
  const wx = ev.clientX - wrap.getBoundingClientRect().left;
  const wy = ev.clientY - wrap.getBoundingClientRect().top;
  off.x = wx - (wx - off.x) * (sc/prev);
  off.y = wy - (wy - off.y) * (sc/prev);
  applyT();
}}, {{passive:false}});

function applyT() {{
  canvas.style.transform = `translate(${{off.x}}px,${{off.y}}px) scale(${{sc}})`;
}}

// ── Fit view ─────────────────────────────────────────────────────────────────
function fitView() {{
  const allX = [...Object.values(srcPos).map(p=>p.x), ...Object.values(tgtPos).map(p=>p.x+CARD_W)];
  const allY = [...Object.values(srcPos).map(p=>p.y), ...Object.values(tgtPos).map(p=>p.y+80)];
  const mnx = Math.min(...allX), mny = Math.min(...allY);
  const mxx = Math.max(...allX), mxy = Math.max(...allY);
  const pad = 60;
  const w = wrap.clientWidth - (document.getElementById('detail').classList.contains('open') ? 340 : 0);
  const h = wrap.clientHeight;
  sc  = Math.min((w-pad*2)/(mxx-mnx), (h-pad*2)/(mxy-mny), 1.5);
  off.x = pad - mnx*sc + (w-pad*2-(mxx-mnx)*sc)/2;
  off.y = pad - mny*sc + (h-pad*2-(mxy-mny)*sc)/2;
  applyT();
}}

// ── Kolom-labels ──────────────────────────────────────────────────────────────
function locLabel(path) {{
  if (!path || path === '?') return 'Bronnen';
  const labels = path.split(',')
    .map(p => {{
      p = p.trim();
      const parts = p.split('/').filter(Boolean);
      const last  = parts[parts.length - 1] || '';
      return last.replace(/\.ldm$/i, '') || parts[0] || p;
    }})
    .filter((v, i, a) => v && a.indexOf(v) === i);
  return labels.join(' / ') || path;
}}

function addColLabels() {{
  const srcLbl = document.createElement('div');
  srcLbl.className = 'col-label';
  srcLbl.style.left = (COL_SRC_X) + 'px';
  srcLbl.textContent = locLabel(META.source_location);
  canvas.appendChild(srcLbl);

  const tgtLbl = document.createElement('div');
  tgtLbl.className = 'col-label';
  tgtLbl.style.left = (COL_TGT_X) + 'px';
  tgtLbl.textContent = locLabel(META.target_location);
  canvas.appendChild(tgtLbl);
}}

// ── Init ──────────────────────────────────────────────────────────────────────
addColLabels();
srcsSorted.forEach(s => makeSrcCard(s));
TARGETS.forEach(t => makeTgtCard(t));
applyT();
setTimeout(() => {{ draw(); fitView(); }}, 120);

// Klik op achtergrond → reset
canvas.addEventListener('click', ev => {{
  if (ev.target === canvas || ev.target === svg) {{
    resetHighlight();
    closeDetail();
  }}
}});
</script>
</body>
</html>
"""


def render_lineage(data: dict, title: str) -> str:
    ld = build_lineage_data(data)

    meta = {
        'source_location': ld['source_location'],
        'target_location': ld['target_location'],
    }

    return LINEAGE_HTML.format(
        title        = title,
        sources_json = json.dumps(ld['sources'],  ensure_ascii=False),
        targets_json = json.dumps(ld['targets'],  ensure_ascii=False),
        meta_json    = json.dumps(meta,            ensure_ascii=False),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("=" * 60)
    log.info("MSL Lineage Visualizer gestart")

    msl_path = find_msl_file()

    try:
        tree = ET.parse(msl_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        log.error("XML parsefout in %s: %s", msl_path.name, exc)
        sys.exit(1)

    validate_msl(root, msl_path)

    data    = parse_msl(root)

    title       = msl_path.stem
    html        = render_lineage(data, title)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{title}_Lineage.html"
    output_path.write_text(html, encoding='utf-8')

    ld = build_lineage_data(data)
    log.info("─" * 60)
    log.info("Lineage diagram gegenereerd: %s", output_path.name)
    log.info("  Bronrecords    : %d (%d primair)",
             len(data['all_sources']),
             sum(1 for s in ld['sources'] if s['primary']))
    log.info("  Doeltabellen   : %d", len(data['target_mappings']))
    log.info("  Edges (lijnen) : %d", sum(len(t['edges']) for t in ld['targets']))
    log.info("  Output grootte : %d bytes", output_path.stat().st_size)
    log.info("─" * 60)


if __name__ == '__main__':
    main()
