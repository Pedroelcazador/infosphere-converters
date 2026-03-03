#!/usr/bin/env python3
# Versie: 2026-03-03 15:00
"""
IBM InfoSphere Data Architect — LDM XML → Markdown + interactieve ERD (HTML)

Gebruik:
  python ldm_convert.py

Logica:
  - 0 of >1 XML bestanden in input/ → fout in logbestand
  - XML is geen LDM export → fout in logbestand
  - Succesvol → <modelnaam>_Datamodel.md, .html en _ERD.html in output/
"""

import sys
import re
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'ldm_convert.log'

sys.path.insert(0, str(ROOT_DIR))
from md_to_html import md_to_html as _md_to_html

# ---------------------------------------------------------------------------
# Logging instellen
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
# Hulpfuncties
# ---------------------------------------------------------------------------
DIM_PREFIXES = ('DIM ', 'Dim ')
DIM_EXACT = {
    'Commit Time', 'Mutatie Volgnummer',
    'Start Datum Geldigheid', 'Eind Datum Geldigheid',
    'Start Datum Administratie', 'Eind Datum Administratie',
    'DIM Start Datum Geldigheid', 'DIM Eind Datum Geldigheid',
    'DIM Start Datum Administratie', 'DIM Eind Datum Administratie',
    'DIM Start Datum', 'DIM Eind Datum',
    'Dim Start Datum Geldigheid', 'Dim Eind datum Geldigheid',
    'Dim Start Datum Administratie', 'Dim Eind Datum Administratie',
}


def is_dim_meta(name: str) -> bool:
    return any(name.startswith(p) for p in DIM_PREFIXES) or name in DIM_EXACT


def get_prop(element, name: str, default: str = '') -> str:
    p = element.find(f'properties/property[@name="{name}"]')
    if p is not None:
        return (p.get('value') or '').strip().replace('\r\n', ' ').replace('\n', ' ')
    return default


def escape_md(text: str) -> str:
    return text.replace('|', '\\|').replace('\n', ' ').strip()


def make_anchor(text: str) -> str:
    """Genereer een HTML anchor-naam die overeenkomt met de inhoudsopgave-links."""
    return re.sub(r'[^a-z0-9\-]', '', text.lower().replace(' ', '-'))


def multiplicity_label(child_mult: str, parent_mult: str) -> str:
    m = {
        'ZERO_TO_MANY': '0..*',
        'ZERO_TO_ONE':  '0..1',
        'ONE':          '1',
        'ONE_TO_MANY':  '1..*',
    }
    return f"{m.get(child_mult, child_mult)} → {m.get(parent_mult, parent_mult)}"


# ---------------------------------------------------------------------------
# Validatie
# ---------------------------------------------------------------------------
def find_xml_file() -> Path:
    """Zoek precies één XML bestand in de input/ map."""
    xml_files = list(INPUT_DIR.glob('*.xml'))

    if len(xml_files) == 0:
        log.error("Geen XML bestand gevonden in %s", INPUT_DIR)
        log.error("Leg één IBM Data Architect LDM XML bestand in de input/ map en probeer opnieuw.")
        sys.exit(1)

    if len(xml_files) > 1:
        names = ', '.join(f.name for f in xml_files)
        log.error("Meer dan één XML bestand gevonden: %s", names)
        log.error("Zorg dat er precies één XML bestand in de input/ map staat.")
        sys.exit(1)

    log.info("XML bestand gevonden: %s", xml_files[0].name)
    return xml_files[0]


def validate_ldm(root: ET.Element, xml_path: Path) -> None:
    """Controleer of het XML een geldig LDM export is."""
    errors = []

    if root.tag != 'logicalModelElement':
        errors.append(
            f"Root element is '{root.tag}', verwacht 'logicalModelElement'. "
            "Dit lijkt geen IBM Data Architect LDM export te zijn."
        )

    entities = root.findall('.//logicalModelElement[@type="Entity"]')
    if not entities:
        errors.append("Geen entiteiten (type='Entity') gevonden. "
                      "Dit is mogelijk een DataStage job-export of ander XML formaat.")

    ds_indicators = root.findall('.//{*}DSJobDef') + root.findall('.//job[@type]')
    if ds_indicators:
        errors.append("DataStage job-definities gevonden — dit is een DataStage export, geen LDM bestand.")

    if errors:
        for err in errors:
            log.error("Validatiefout: %s", err)
        log.error("Conversie afgebroken voor bestand: %s", xml_path.name)
        sys.exit(1)

    log.info("Validatie geslaagd — %d entiteiten gevonden", len(entities))


# ---------------------------------------------------------------------------
# Parseren
# ---------------------------------------------------------------------------
def parse_model(root: ET.Element) -> dict:
    model_info = {}
    mi = root.find('.//modelElement[@type="Model Information"]')
    if mi is not None:
        for p in mi.findall('properties/property'):
            model_info[p.get('name')] = p.get('value', '')

    entity_index = {
        e.get('id'): e.get('name')
        for e in root.findall('.//logicalModelElement[@type="Entity"]')
    }

    entities = []
    stats = {
        'entities': 0,
        'total_attributes': 0,
        'dim_meta_attributes': 0,
        'foreign_keys': 0,
        'entities_without_description': [],
    }

    for e in root.findall('.//logicalModelElement[@type="Entity"]'):
        name        = e.get('name')
        label       = get_prop(e, 'Label')
        description = get_prop(e, 'Description')

        if not description:
            stats['entities_without_description'].append(name)

        attributes = []
        for a in e.findall('logicalModelElement[@type="Attribute"]'):
            attr = {
                'name':        a.get('name'),
                'label':       get_prop(a, 'Label'),
                'datatype':    get_prop(a, 'Data Type'),
                'pk':          get_prop(a, 'Is Part Of PrimaryKey') == 'true',
                'required':    get_prop(a, 'Is Required') == 'true',
                'derived':     get_prop(a, 'Is Derived') == 'true',
                'surrogate':   get_prop(a, 'Is Surrogate Key') == 'true',
                'description': get_prop(a, 'Description'),
                'dim_meta':    is_dim_meta(a.get('name', '')),
            }
            attributes.append(attr)
            stats['total_attributes'] += 1
            if attr['dim_meta']:
                stats['dim_meta_attributes'] += 1

        pk_attrs = []
        pk_elem = e.find('logicalModelElement[@type="PrimaryKey"]')
        if pk_elem is not None:
            for p in pk_elem.findall('properties/property[@name="Key Attribute"]'):
                pk_attrs.append(p.get('value', ''))

        foreign_keys = []
        for r in e.findall('logicalModelElement[@type="Relationship"]'):
            child_prop  = r.find('properties/property[@name="Child Table"]')
            parent_prop = r.find('properties/property[@name="Parent Table"]')
            if child_prop is None or parent_prop is None:
                continue
            if child_prop.get('linkID', '') != e.get('id'):
                continue

            child_mult  = ''
            parent_mult = ''
            for p in r.findall('properties/property'):
                if p.get('name') == 'Child Multiplicity':
                    child_mult = p.get('value', '')
                elif p.get('name') == 'Parent Multiplicity':
                    parent_mult = p.get('value', '')

            parent_name = entity_index.get(
                parent_prop.get('linkID', ''),
                parent_prop.get('value', '?')
            )
            foreign_keys.append({
                'name':         r.get('name'),
                'parent_table': parent_name,
                'child_mult':   child_mult,
                'parent_mult':  parent_mult,
                'identifying':  get_prop(r, 'Is Identifying Relationship') == 'true',
            })
            stats['foreign_keys'] += 1

        entities.append({
            'name':        name,
            'id':          e.get('id'),
            'label':       label,
            'description': description,
            'attributes':  attributes,
            'pk_attrs':    pk_attrs,
            'fks':         foreign_keys,
        })
        stats['entities'] += 1

    return {
        'model_name': root.get('name', 'Onbekend model'),
        'model_info': model_info,
        'entities':   entities,
        'stats':      stats,
    }


# ---------------------------------------------------------------------------
# Hiërarchische layout berekenen
# ---------------------------------------------------------------------------
def compute_layout(entities: list) -> dict:
    """
    Berekent x/y posities via topologische niveaubepaling.

    Niveau 0 = root-entiteiten (geen FK naar andere entiteit)
    Niveau N = maximale afstand tot een root via FK-keten

    Geeft een dict terug: {entity_name: {'x': int, 'y': int}}
    """
    CARD_W  = 240   # breedte van een entiteitskaart (px)
    CARD_H  = 160   # geschatte hoogte (wordt dynamisch groter bij veel attrs)
    H_GAP   = 40    # horizontale ruimte tussen kaarten
    V_GAP   = 80    # verticale ruimte tussen niveaus

    names = [e['name'] for e in entities]

    # Bouw parent-set per entiteit: welke entiteiten zijn zijn ouder?
    parents: dict[str, set] = {n: set() for n in names}
    for e in entities:
        for fk in e['fks']:
            p = fk['parent_table']
            if p in parents and p != e['name']:
                parents[e['name']].add(p)

    # Topologische niveaubepaling (Kahn-achtig, maar gebaseerd op max-diepte)
    levels: dict[str, int] = {}

    def get_level(name: str, visited: set) -> int:
        if name in levels:
            return levels[name]
        if name in visited:          # circulaire relatie: zet op huidig niveau
            return 0
        visited = visited | {name}
        if not parents[name]:
            levels[name] = 0
            return 0
        lvl = max(get_level(p, visited) for p in parents[name]) + 1
        levels[name] = lvl
        return lvl

    for n in names:
        get_level(n, set())

    # Groepeer per niveau
    level_groups: dict[int, list] = defaultdict(list)
    for n, lvl in levels.items():
        level_groups[lvl].append(n)

    # Sorteer entiteiten binnen een niveau op naam voor consistentie
    for lvl in level_groups:
        level_groups[lvl].sort()

    # Bereken posities
    positions = {}
    for lvl in sorted(level_groups.keys()):
        group  = level_groups[lvl]
        n      = len(group)
        total_w = n * CARD_W + (n - 1) * H_GAP
        start_x = max(0, -total_w // 2 + 900)   # gecentreerd rond x=900

        y = lvl * (CARD_H + V_GAP) + 20
        for i, name in enumerate(group):
            x = start_x + i * (CARD_W + H_GAP)
            positions[name] = {'x': x, 'y': y}

    return positions


# ---------------------------------------------------------------------------
# ERD HTML renderen
# ---------------------------------------------------------------------------
ERD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<title>{model_name} — ERD</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#eef2f7; color:#1a2a3a; font-family:Arial,sans-serif; overflow:hidden; }}

  /* ── Toolbar ── */
  #toolbar {{
    position:fixed; top:0; left:0; right:0; height:52px;
    background:#005b9a; display:flex; align-items:center;
    padding:0 16px; gap:10px; z-index:200;
    box-shadow:0 2px 8px rgba(0,0,0,0.2);
  }}
  #uwv-logo {{
    font-size:18px; font-weight:700; background:#fff; color:#005b9a;
    padding:2px 9px; border-radius:3px; line-height:1.4; flex-shrink:0;
  }}
  #toolbar h1 {{ font-size:13px; color:#cce0f5; flex:1; font-weight:400; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  #toolbar h1 strong {{ color:#fff; font-weight:700; }}
  /* ── Attribuutmodus-knoppen ── */
  #attr-mode-group {{ display:flex; gap:4px; align-items:center; border-left:1px solid rgba(255,255,255,0.2); padding-left:10px; flex-shrink:0; }}
  #attr-mode-group span {{ font-size:10px; color:#a8cce8; margin-right:2px; white-space:nowrap; }}
  .mode-btn {{
    padding:4px 9px; border-radius:4px; border:1.5px solid rgba(255,255,255,0.3);
    background:rgba(255,255,255,0.08); color:rgba(255,255,255,0.7); cursor:pointer;
    font-size:11px; font-family:inherit; font-weight:600; white-space:nowrap;
  }}
  .mode-btn:hover {{ background:rgba(255,255,255,0.18); color:#fff; }}
  .mode-btn.active {{ background:rgba(255,255,255,0.28); color:#fff; border-color:rgba(255,255,255,0.75); }}
  #legend {{ display:flex; gap:14px; align-items:center; font-size:11px; color:#cce0f5; flex-shrink:0; }}
  .leg {{ display:flex; align-items:center; gap:5px; }}
  .leg-solid {{ width:22px; height:2px; background:#fff; border-radius:1px; }}
  .leg-dashed {{ width:22px; height:0; border-top:2.5px dashed #f9b46a; }}
  .btn {{
    padding:5px 11px; border-radius:4px; border:1.5px solid rgba(255,255,255,0.35);
    background:rgba(255,255,255,0.1); color:#fff; cursor:pointer;
    font-size:12px; font-family:inherit; font-weight:600; white-space:nowrap; flex-shrink:0;
  }}
  .btn:hover {{ background:rgba(255,255,255,0.22); }}

  /* ── Zoekbalk ── */
  #search-wrap {{ position:relative; flex-shrink:0; }}
  #search {{
    padding:4px 28px 4px 9px; border-radius:4px; border:1.5px solid rgba(255,255,255,0.35);
    background:rgba(255,255,255,0.12); color:#fff; font-size:12px; font-family:inherit;
    width:160px; outline:none;
  }}
  #search::placeholder {{ color:rgba(255,255,255,0.5); }}
  #search:focus {{ background:rgba(255,255,255,0.2); border-color:rgba(255,255,255,0.7); }}
  #search-clear {{
    position:absolute; right:6px; top:50%; transform:translateY(-50%);
    color:rgba(255,255,255,0.6); cursor:pointer; font-size:14px; display:none;
  }}
  #search-results {{
    position:absolute; top:calc(100% + 4px); left:0; min-width:220px;
    background:#fff; border:1px solid #c0d4e8; border-radius:4px;
    box-shadow:0 4px 14px rgba(0,0,0,0.15); z-index:300; max-height:260px; overflow-y:auto;
    display:none;
  }}
  .sr-item {{
    padding:7px 12px; font-size:12px; color:#1a2a3a; cursor:pointer; border-bottom:1px solid #eef2f7;
  }}
  .sr-item:last-child {{ border-bottom:none; }}
  .sr-item:hover {{ background:#e8f2fb; }}
  .sr-highlight {{ background:#fff3b0; border-radius:2px; }}

  /* ── Canvas ── */
  #canvas-wrap {{
    position:fixed; top:52px; left:0; right:0; bottom:0; overflow:hidden;
    background:#eef2f7;
    background-image:radial-gradient(circle,#c5d5e5 1px,transparent 1px);
    background-size:22px 22px;
  }}
  #canvas {{ position:absolute; top:0; left:0; }}
  svg#lines {{ position:absolute; top:0; left:0; pointer-events:none; overflow:visible; }}

  /* ── Entiteiten ── */
  .entity {{
    position:absolute; background:#fff;
    border:2px solid #005b9a; border-radius:6px;
    min-width:230px; max-width:280px;
    cursor:default; user-select:none;
    box-shadow:0 2px 8px rgba(0,91,154,0.13);
    transition:box-shadow 0.15s, opacity 0.2s;
  }}
  .entity:hover {{ box-shadow:0 4px 18px rgba(0,91,154,0.28); }}
  .entity.dragging {{ box-shadow:0 8px 28px rgba(0,91,154,0.36); z-index:999; }}
  .entity.dimmed {{ opacity:0.22; }}
  .entity.highlighted {{ box-shadow:0 0 0 3px #f5a623, 0 4px 18px rgba(0,91,154,0.28); }}
  .entity.search-match {{ box-shadow:0 0 0 3px #2ecc71, 0 4px 18px rgba(0,91,154,0.28); }}

  .entity-header {{
    background:#005b9a; padding:8px 11px;
    border-radius:4px 4px 0 0; cursor:move;
  }}
  .entity.highlighted .entity-header {{ background:#c05000; }}
  .entity-name {{ font-size:12px; font-weight:700; color:#fff; }}
  .entity-label {{ font-size:9px; color:#99c5e8; margin-top:2px; font-family:'Courier New',monospace; }}

  .entity-attrs {{ padding:2px 0; overflow:hidden; }}
  .entity-attrs.collapsed {{ max-height:0 !important; }}

  .attr-section-label {{
    font-size:9px; font-weight:700; color:#005b9a;
    padding:4px 10px 2px; text-transform:uppercase; letter-spacing:0.5px;
    background:#f0f7ff; border-bottom:1px solid #dde8f0;
  }}
  .attr-row {{
    display:flex; align-items:center; padding:3px 10px; gap:5px;
    font-size:10px; border-bottom:1px solid #e8eff6;
  }}
  .attr-row:last-child {{ border-bottom:none; }}
  .attr-row:hover {{ background:#f0f7ff; }}
  .attr-pk {{ color:#004a80; font-weight:700; }}
  .attr-sk {{ color:#005530; font-weight:600; }}
  .attr-meta {{ color:#8899aa; font-style:italic; }}
  .attr-normal {{ color:#334455; }}
  .attr-name {{ flex:1; }}
  .attr-type {{ color:#8899aa; font-size:9px; font-family:'Courier New',monospace; white-space:nowrap; }}

  .toggle-btn {{
    display:block; text-align:center; padding:4px 10px;
    font-size:10px; font-weight:600; color:#005b9a;
    border-top:1px solid #d0dce8; cursor:pointer;
    background:#f5f9fd; border-radius:0 0 4px 4px;
  }}
  .toggle-btn:hover {{ background:#e4f0fb; }}

  /* ── Tooltip ── */
  #tooltip {{
    position:fixed; background:#1c2c3c; border:1px solid #005b9a;
    padding:8px 12px; border-radius:4px; font-size:11px; color:#d8eaf8;
    max-width:320px; pointer-events:none; display:none; z-index:1000;
    line-height:1.5; box-shadow:0 4px 12px rgba(0,0,0,0.25);
  }}

  /* ── Info-balk ── */
  #info-panel {{
    position:fixed; bottom:14px; left:50%; transform:translateX(-50%);
    background:rgba(0,40,80,0.82); border-radius:5px; backdrop-filter:blur(4px);
    padding:6px 16px; font-size:11px; color:#cce4f8; z-index:100; white-space:nowrap;
  }}

  /* ── Mini-map ── */
  #minimap {{
    position:fixed; bottom:14px; right:16px; z-index:150;
    background:rgba(255,255,255,0.93); border:1.5px solid #b0c8e0;
    border-radius:5px; box-shadow:0 2px 8px rgba(0,0,0,0.15);
    overflow:hidden; cursor:pointer;
  }}
  #minimap canvas {{ display:block; }}
  #mm-viewport {{
    position:absolute; top:0; left:0;
    border:2px solid #e05000; border-radius:2px;
    pointer-events:none; background:rgba(224,80,0,0.08);
  }}
</style>
</head>
<body>
<div id="toolbar">
  <div id="uwv-logo">UWV</div>
  <h1><strong>{model_name}</strong> — Logisch Datamodel ERD</h1>
  <div id="attr-mode-group">
    <span>Attrs:</span>
    <button class="mode-btn {mode_none_active}"  onclick="setMode('none')"  title="Alleen entiteitsnamen, geen attributen">None</button>
    <button class="mode-btn {mode_keys_active}"  onclick="setMode('keys')"  title="Alleen PK- en FK-attributen">Keys</button>
    <button class="mode-btn {mode_all_active}"   onclick="setMode('all')"   title="Alle attributen inclusief DIM-meta">All</button>
  </div>
  <div id="legend">
    <div class="leg"><div class="leg-solid"></div><span>Non-identifying</span></div>
    <div class="leg"><div class="leg-dashed"></div><span>Identifying</span></div>
  </div>
  <div id="search-wrap">
    <input id="search" type="text" placeholder="🔍 Zoek entiteit…" autocomplete="off">
    <span id="search-clear">✕</span>
    <div id="search-results"></div>
  </div>
  <button class="btn" onclick="resetLayout()">↺ Reset</button>
  <button class="btn" onclick="fitView()">⊡ Fit</button>
</div>

<div id="canvas-wrap">
  <div id="canvas"><svg id="lines"></svg></div>
</div>
<div id="tooltip"></div>
<div id="info-panel">Drag • Klik header voor attributen • Hover voor omschrijving • Scroll = zoom • Klik entiteit = highlight relaties</div>
<div id="minimap"><canvas id="mm-canvas"></canvas><div id="mm-viewport"></div></div>

<script>
let   ATTR_MODE  = '{init_mode}';   // 'none' | 'keys' | 'all'
const ENTITIES   = {entities_json};
const RELS       = {rels_json};
const INIT_POS   = {positions_json};
const STORAGE_KEY = 'erd_pos_{model_key}';

// ── State ──────────────────────────────────────────────────────────────────
let pos      = {{}};
let off      = {{x:0, y:0}}, sc = 0.75;
let panning  = false, ps = {{x:0, y:0}};
let allExp   = false;
let hoveredId = null;   // voor relatie-highlight
let svgNodes = {{}};     // gecachte SVG-elementen per relatie

const canvas = document.getElementById('canvas');
const svg    = document.getElementById('lines');
const wrap   = document.getElementById('canvas-wrap');
const tip    = document.getElementById('tooltip');
const mmCvs  = document.getElementById('mm-canvas');
const mmVp   = document.getElementById('mm-viewport');
const mmCtx  = mmCvs.getContext('2d');

// Bouw adjacency voor highlight
const adjMap = {{}};  // id → Set van verbonden id's
ENTITIES.forEach(e => {{ adjMap[e.id] = new Set(); }});
RELS.forEach(r => {{ adjMap[r.p]?.add(r.c); adjMap[r.c]?.add(r.p); }});

// ── Posities laden (localStorage → INIT_POS fallback) ─────────────────────
function loadPos() {{
  try {{
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {{
      const parsed = JSON.parse(saved);
      // Valideer: alle entiteiten moeten een positie hebben
      if (ENTITIES.every(e => parsed[e.id])) return parsed;
    }}
  }} catch(e) {{}}
  return JSON.parse(JSON.stringify(INIT_POS));
}}

function savePos() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(pos)); }} catch(e) {{}}
}}

// ── Entiteit aanmaken ──────────────────────────────────────────────────────
function makeEnt(e) {{
  const el = document.createElement('div');
  el.className = 'entity';
  el.id = 'ent_' + e.id;
  el.style.left = pos[e.id].x + 'px';
  el.style.top  = pos[e.id].y + 'px';

  // Header
  const hdr = document.createElement('div');
  hdr.className = 'entity-header';
  hdr.innerHTML = `<div class="entity-name">${{e.name}}</div>`
                + (e.label ? `<div class="entity-label">${{e.label}}</div>` : '');
  if (e.desc) {{
    hdr.addEventListener('mousemove', ev => showTip(ev, e.desc));
    hdr.addEventListener('mouseleave', hideTip);
  }}
  el.appendChild(hdr);

  // Attribuutblok
  const ad = document.createElement('div');
  ad.className = 'entity-attrs';
  ad.dataset.entId = e.id;
  renderAttrs(ad, e);
  el.appendChild(ad);

  // Toggle knop
  const tog = document.createElement('div');
  tog.className = 'toggle-btn';
  tog.textContent = ATTR_MODE !== 'none' ? '▴ verbergen' : '▾ attributen tonen';
  tog.addEventListener('click', () => {{
    if (ad._expanded) {{
      ad._expanded = false;
      renderAttrs(ad, e);
      tog.textContent = ad.classList.contains('collapsed') ? '▾ attributen tonen' : '▴ verbergen';
    }} else {{
      ad._expanded = true;
      ad.classList.remove('collapsed');
      while (ad.firstChild) ad.removeChild(ad.firstChild);
      const funcA = e.attrs.filter(a => !a.meta);
      const metaA = e.attrs.filter(a => a.meta);
      funcA.forEach(a => ad.appendChild(makeAttrRow(a)));
      if (metaA.length) {{
        const lbl = document.createElement('div');
        lbl.className = 'attr-section-label';
        lbl.textContent = 'DIM / bitemporale velden';
        ad.appendChild(lbl);
        metaA.forEach(a => ad.appendChild(makeAttrRow(a, true)));
      }}
      tog.textContent = '▴ verbergen';
    }}
    setTimeout(() => {{ draw(); drawMinimap(); }}, 320);
  }});
  el.appendChild(tog);

  // Klik op entiteit → relatie-highlight
  el.addEventListener('click', ev => {{
    if (ev.target.closest('.toggle-btn')) return;
    if (ev.target.closest('.attr-row')) return;
    const isActive = hoveredId === e.id;
    setHighlight(isActive ? null : e.id);
  }});

  drag(el, e.id, hdr);
  canvas.appendChild(el);
}}

// ── Attribuutmodus ────────────────────────────────────────────────────────
function renderAttrs(container, e) {{
  while (container.firstChild) container.removeChild(container.firstChild);
  if (ATTR_MODE === 'none') return;

  const visibleAttrs = e.attrs.filter(a => {{
    if (ATTR_MODE === 'keys') return a.pk || a.fk;
    return true;  // 'all'
  }});

  const funcAttrs = visibleAttrs.filter(a => !a.meta);
  const metaAttrs = visibleAttrs.filter(a => a.meta);

  funcAttrs.forEach(a => container.appendChild(makeAttrRow(a)));
  if (ATTR_MODE === 'all' && metaAttrs.length) {{
    const lbl = document.createElement('div');
    lbl.className = 'attr-section-label';
    lbl.textContent = 'DIM / bitemporale velden';
    container.appendChild(lbl);
    metaAttrs.forEach(a => container.appendChild(makeAttrRow(a, true)));
  }}
}}

function setMode(mode) {{
  ATTR_MODE = mode;
  // Knop-styling updaten
  document.querySelectorAll('.mode-btn').forEach(btn => {{
    btn.classList.toggle('active', btn.getAttribute('onclick').includes("'" + mode + "'"));
  }});
  // Alle entiteiten opnieuw renderen
  ENTITIES.forEach(e => {{
    const ad = document.querySelector('.entity-attrs[data-ent-id="' + e.id + '"]');
    if (ad) renderAttrs(ad, e);
  }});
  ENTITIES.forEach(e => {{
    const el  = document.getElementById('ent_' + e.id);
    const ad  = el?.querySelector('.entity-attrs');
    const tog = el?.querySelector('.toggle-btn');
    if (!el || !ad || !tog) return;
    ad._expanded = false;
    ad._userCollapsed = false;
    if (mode === 'none') {{
      ad.classList.add('collapsed');
      tog.textContent = '▾ attributen tonen';
    }} else {{
      ad.classList.remove('collapsed');
      tog.textContent = '▴ verbergen';
    }}
  }});
  setTimeout(() => {{ draw(); drawMinimap(); }}, 50);
}}

function makeAttrRow(a, isMeta=false) {{
  const row = document.createElement('div');
  row.className = 'attr-row';
  const icon = a.pk ? '🔑 ' : a.sk ? '⚙ ' : '';
  const cls  = a.pk ? 'attr-pk' : a.sk ? 'attr-sk' : isMeta ? 'attr-meta' : 'attr-normal';
  row.innerHTML = `<span class="attr-name ${{cls}}">${{icon}}${{a.name}}</span>`
                + `<span class="attr-type">${{a.dtype}}</span>`;
  if (a.desc) {{
    row.addEventListener('mousemove', ev => showTip(ev, a.desc));
    row.addEventListener('mouseleave', hideTip);
  }}
  return row;
}}

// ── Highlight relaties ─────────────────────────────────────────────────────
function setHighlight(id) {{
  hoveredId = id;
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    if (!el) return;
    if (!id) {{
      el.classList.remove('dimmed', 'highlighted');
    }} else if (e.id === id) {{
      el.classList.remove('dimmed'); el.classList.add('highlighted');
    }} else if (adjMap[id]?.has(e.id)) {{
      el.classList.remove('dimmed', 'highlighted');
    }} else {{
      el.classList.add('dimmed'); el.classList.remove('highlighted');
    }}
  }});
  draw();
}}

// ── Drag ──────────────────────────────────────────────────────────────────
function drag(el, id, handle) {{
  let on=false, sx,sy,ex,ey;
  handle.addEventListener('mousedown', ev => {{
    ev.preventDefault(); on=true; el.classList.add('dragging');
    sx=ev.clientX; sy=ev.clientY; ex=pos[id].x; ey=pos[id].y;
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  }});
  function mv(ev) {{
    if (!on) return;
    pos[id].x = ex + (ev.clientX-sx)/sc;
    pos[id].y = ey + (ev.clientY-sy)/sc;
    el.style.left = pos[id].x + 'px';
    el.style.top  = pos[id].y + 'px';
    draw(); drawMinimap();
  }}
  function up() {{
    on=false; el.classList.remove('dragging');
    document.removeEventListener('mousemove', mv);
    document.removeEventListener('mouseup', up);
    savePos();
  }}
}}

// ── Tooltip (volgt muis) ───────────────────────────────────────────────────
function showTip(ev, text) {{
  tip.textContent = text; tip.style.display = 'block';
  tip.style.left = Math.min(ev.clientX+14, window.innerWidth-340) + 'px';
  tip.style.top  = Math.min(ev.clientY+14, window.innerHeight-80) + 'px';
}}
function hideTip() {{ tip.style.display = 'none'; }}

// ── SVG – edge-berekening ─────────────────────────────────────────────────
function edgePt(id, tid) {{
  const el  = document.getElementById('ent_' + id);
  const tel = document.getElementById('ent_' + tid);
  if (!el || !tel) return null;
  const cx = pos[id].x  + el.offsetWidth/2,  cy = pos[id].y  + el.offsetHeight/2;
  const tx = pos[tid].x + tel.offsetWidth/2,  ty = pos[tid].y + tel.offsetHeight/2;
  const dx = tx-cx, dy = ty-cy;
  const w = el.offsetWidth/2, h = el.offsetHeight/2;
  return Math.abs(dx)*h > Math.abs(dy)*w
    ? {{x: cx + Math.sign(dx)*w,     y: cy + dy/(Math.abs(dx)/w)}}
    : {{x: cx + dx/(Math.abs(dy)/h), y: cy + Math.sign(dy)*h}};
}}

// ── SVG – teken met DOM-elementen (geen innerHTML) ─────────────────────────
function ensureSvgGroup(key) {{
  if (!svgNodes[key]) {{
    const g = document.createElementNS('http://www.w3.org/2000/svg','g');
    g.dataset.key = key;
    svg.appendChild(g);
    svgNodes[key] = g;
  }}
  return svgNodes[key];
}}

function svgEl(tag, attrs) {{
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k,v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}}

function draw() {{
  // SVG groot genoeg maken
  const mw = Math.max(...ENTITIES.map(e => (pos[e.id]?.x||0) + 320)) + 200;
  const mh = Math.max(...ENTITIES.map(e => (pos[e.id]?.y||0) + 400)) + 200;
  svg.setAttribute('width', mw); svg.setAttribute('height', mh);

  RELS.forEach((r, i) => {{
    const key  = `r${{i}}`;
    const p1   = edgePt(r.p, r.c);
    const p2   = edgePt(r.c, r.p);
    const g    = ensureSvgGroup(key);

    if (!p1 || !p2) {{ g.style.display='none'; return; }}
    g.style.display = '';

    const isActive = !hoveredId || r.p === hoveredId || r.c === hoveredId;
    const col   = r.i ? '#c04000' : '#005b9a';
    const dash  = r.i ? '7,4' : 'none';
    const alpha = isActive ? 0.85 : 0.12;

    const dx = p2.x-p1.x, dy = p2.y-p1.y;
    const len = Math.sqrt(dx*dx+dy*dy) || 1;
    const bend = Math.min(60, len*0.22);
    const nx = -dy/len*bend, ny = dx/len*bend;
    const mx = (p1.x+p2.x)/2+nx, my = (p1.y+p2.y)/2+ny;

    // Crow's foot (N-end = child = p2)
    const ang  = Math.atan2(p2.y-p1.y, p2.x-p1.x);
    const cf1x = p2.x - Math.cos(ang+0.3)*13, cf1y = p2.y - Math.sin(ang+0.3)*13;
    const cf2x = p2.x - Math.cos(ang-0.3)*13, cf2y = p2.y - Math.sin(ang-0.3)*13;
    const cfbx = p2.x - Math.cos(ang)*15,     cfby = p2.y - Math.sin(ang)*15;

    // 1-bar (1-end = parent = p1)
    const b1x = p1.x + Math.cos(ang)*12, b1y = p1.y + Math.sin(ang)*12;
    const bpx = Math.sin(ang)*7,         bpy = -Math.cos(ang)*7;

    // Label halverwege de lijn
    const pname = ENTITIES.find(e=>e.id===r.p)?.name || '';
    const cname = ENTITIES.find(e=>e.id===r.c)?.name || '';
    const labelText = `${{pname}} → ${{cname}}`;
    const labelAngle = Math.atan2(dy, dx) * 180/Math.PI;
    const flip = labelAngle > 90 || labelAngle < -90;

    // Leeg de groep en herbouw (enkel bij wijziging door positie-update)
    while (g.firstChild) g.removeChild(g.firstChild);

    g.appendChild(svgEl('path', {{
      d: `M${{p1.x}},${{p1.y}} Q${{mx}},${{my}} ${{p2.x}},${{p2.y}}`,
      fill:'none', stroke:col, 'stroke-width':'1.8',
      'stroke-dasharray':dash, opacity:alpha
    }}));
    // 1-bar
    g.appendChild(svgEl('line', {{ x1:b1x-bpx, y1:b1y-bpy, x2:b1x+bpx, y2:b1y+bpy, stroke:col, 'stroke-width':'1.8', opacity:alpha }}));
    // crow's foot
    g.appendChild(svgEl('line', {{ x1:cf1x, y1:cf1y, x2:p2.x, y2:p2.y, stroke:col, 'stroke-width':'1.8', opacity:alpha }}));
    g.appendChild(svgEl('line', {{ x1:cf2x, y1:cf2y, x2:p2.x, y2:p2.y, stroke:col, 'stroke-width':'1.8', opacity:alpha }}));
    g.appendChild(svgEl('line', {{
      x1:cfbx-Math.sin(ang)*6, y1:cfby+Math.cos(ang)*6,
      x2:cfbx+Math.sin(ang)*6, y2:cfby-Math.cos(ang)*6,
      stroke:col, 'stroke-width':'1.8', opacity:alpha
    }}));

    // Relatie-label
    if (isActive) {{
      const textPath = svgEl('path', {{
        id:`tp${{key}}`,
        d: flip
          ? `M${{p2.x}},${{p2.y}} Q${{mx}},${{my}} ${{p1.x}},${{p1.y}}`
          : `M${{p1.x}},${{p1.y}} Q${{mx}},${{my}} ${{p2.x}},${{p2.y}}`,
        fill:'none'
      }});
      g.appendChild(textPath);
      const txt = svgEl('text', {{ 'font-size':'9', fill:col, opacity:'0.85', 'font-family':'Arial,sans-serif' }});
      const tp  = svgEl('textPath', {{ href:`#tp${{key}}`, startOffset:'50%', 'text-anchor':'middle' }});
      tp.textContent = labelText;
      txt.appendChild(tp);
      g.appendChild(txt);
    }}
  }});
}}

// ── Pan & zoom ─────────────────────────────────────────────────────────────
wrap.addEventListener('mousedown', ev => {{
  if (ev.target===wrap || ev.target===canvas || ev.target===svg) {{
    panning=true; ps={{x:ev.clientX-off.x, y:ev.clientY-off.y}};
    wrap.style.cursor='grabbing';
  }}
}});
document.addEventListener('mousemove', ev => {{
  if (!panning) return;
  off={{x:ev.clientX-ps.x, y:ev.clientY-ps.y}};
  applyT(); drawMinimap();
}});
document.addEventListener('mouseup', () => {{ panning=false; wrap.style.cursor=''; }});
wrap.addEventListener('wheel', ev => {{
  ev.preventDefault();
  const prevSc = sc;
  sc = Math.max(0.15, Math.min(3.0, sc * (ev.deltaY>0 ? 0.9 : 1.11)));
  // Zoom naar muispositie
  const wx = ev.clientX - wrap.getBoundingClientRect().left;
  const wy = ev.clientY - wrap.getBoundingClientRect().top;
  off.x = wx - (wx - off.x) * (sc/prevSc);
  off.y = wy - (wy - off.y) * (sc/prevSc);
  applyT(); drawMinimap();
}}, {{passive:false}});

function applyT() {{
  canvas.style.transform = `translate(${{off.x}}px,${{off.y}}px) scale(${{sc}})`;
  canvas.style.transformOrigin = '0 0';
}}

// ── Knoppen ────────────────────────────────────────────────────────────────
function resetLayout() {{
  pos = JSON.parse(JSON.stringify(INIT_POS));
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    if (el) {{ el.style.left=pos[e.id].x+'px'; el.style.top=pos[e.id].y+'px'; }}
  }});
  off={{x:20,y:10}}; sc=0.75; applyT();
  setTimeout(() => {{ draw(); drawMinimap(); }}, 60);
  savePos();
}}

function toggleAllExpand() {{
  if (ATTR_MODE === 'none') setMode('keys');
}}

function fitView() {{
  // Gebruik echte DOM-afmetingen voor nauwkeurige fit
  let mnx=Infinity, mny=Infinity, mxx=-Infinity, mxy=-Infinity;
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    if (!el) return;
    const x = pos[e.id]?.x||0, y = pos[e.id]?.y||0;
    mnx = Math.min(mnx, x);       mny = Math.min(mny, y);
    mxx = Math.max(mxx, x + el.offsetWidth);
    mxy = Math.max(mxy, y + el.offsetHeight);
  }});
  const pad = 60;
  const w = wrap.clientWidth, h = wrap.clientHeight;
  sc = Math.min((w-pad*2)/(mxx-mnx), (h-pad*2)/(mxy-mny), 1.5);
  off.x = pad - mnx*sc + (w - pad*2 - (mxx-mnx)*sc)/2;
  off.y = pad - mny*sc + (h - pad*2 - (mxy-mny)*sc)/2;
  applyT(); drawMinimap();
}}

// ── Mini-map ───────────────────────────────────────────────────────────────
const MM_W = 180, MM_H = 120;
mmCvs.width = MM_W; mmCvs.height = MM_H;

function drawMinimap() {{
  mmCtx.clearRect(0,0,MM_W,MM_H);
  mmCtx.fillStyle = '#eef2f7';
  mmCtx.fillRect(0,0,MM_W,MM_H);

  // Bepaal bounding box van alle entiteiten
  let mnx=Infinity, mny=Infinity, mxx=0, mxy=0;
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    const x = pos[e.id]?.x||0, y = pos[e.id]?.y||0;
    const w = el ? el.offsetWidth : 240, h = el ? el.offsetHeight : 60;
    mnx=Math.min(mnx,x); mny=Math.min(mny,y);
    mxx=Math.max(mxx,x+w); mxy=Math.max(mxy,y+h);
  }});
  const pad=10;
  const scx = (MM_W-pad*2)/(mxx-mnx||1);
  const scy = (MM_H-pad*2)/(mxy-mny||1);
  const msc = Math.min(scx,scy);

  // Relaties
  mmCtx.strokeStyle='rgba(0,91,154,0.3)'; mmCtx.lineWidth=0.7;
  RELS.forEach(r => {{
    const pe = document.getElementById('ent_'+r.p), ce = document.getElementById('ent_'+r.c);
    if (!pe||!ce) return;
    const px = pad+(pos[r.p].x+pe.offsetWidth/2-mnx)*msc;
    const py = pad+(pos[r.p].y+pe.offsetHeight/2-mny)*msc;
    const cx2= pad+(pos[r.c].x+ce.offsetWidth/2-mnx)*msc;
    const cy2= pad+(pos[r.c].y+ce.offsetHeight/2-mny)*msc;
    mmCtx.beginPath(); mmCtx.moveTo(px,py); mmCtx.lineTo(cx2,cy2); mmCtx.stroke();
  }});

  // Entiteiten
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    const x = pad+(pos[e.id].x-mnx)*msc;
    const y = pad+(pos[e.id].y-mny)*msc;
    const w = (el ? el.offsetWidth : 240)*msc;
    const h = (el ? el.offsetHeight: 60)*msc;
    mmCtx.fillStyle = e.id===hoveredId ? '#c05000' : '#005b9a';
    mmCtx.fillRect(x,y,Math.max(w,3),Math.max(h,3));
  }});

  // Viewport-kader
  const vx = pad+(-off.x/sc-mnx)*msc;
  const vy = pad+(-off.y/sc-mny)*msc;
  const vw = wrap.clientWidth/sc*msc;
  const vh = wrap.clientHeight/sc*msc;
  mmVp.style.left   = Math.max(0,vx)+'px';
  mmVp.style.top    = Math.max(0,vy)+'px';
  mmVp.style.width  = Math.min(vw, MM_W-Math.max(0,vx))+'px';
  mmVp.style.height = Math.min(vh, MM_H-Math.max(0,vy))+'px';
}}

// Klik op minimap → pan naar positie
document.getElementById('minimap').addEventListener('click', ev => {{
  const rect = mmCvs.getBoundingClientRect();
  let mnx=Infinity,mny=Infinity,mxx=0,mxy=0;
  ENTITIES.forEach(e => {{
    const el=document.getElementById('ent_'+e.id);
    const x=pos[e.id]?.x||0, y=pos[e.id]?.y||0;
    const w=el?el.offsetWidth:240, h=el?el.offsetHeight:60;
    mnx=Math.min(mnx,x); mny=Math.min(mny,y);
    mxx=Math.max(mxx,x+w); mxy=Math.max(mxy,y+h);
  }});
  const pad=10, msc=Math.min((MM_W-pad*2)/(mxx-mnx||1),(MM_H-pad*2)/(mxy-mny||1));
  const cx = (ev.clientX-rect.left-pad)/msc+mnx;
  const cy = (ev.clientY-rect.top -pad)/msc+mny;
  off.x = wrap.clientWidth/2  - cx*sc;
  off.y = wrap.clientHeight/2 - cy*sc;
  applyT(); drawMinimap();
}});

// ── Zoekfunctie ────────────────────────────────────────────────────────────
const searchEl  = document.getElementById('search');
const searchRes = document.getElementById('search-results');
const searchClr = document.getElementById('search-clear');

function clearSearchHighlight() {{
  ENTITIES.forEach(e => document.getElementById('ent_'+e.id)?.classList.remove('search-match'));
}}

searchEl.addEventListener('input', () => {{
  const q = searchEl.value.trim().toLowerCase();
  searchClr.style.display = q ? 'block' : 'none';
  clearSearchHighlight();
  searchRes.innerHTML = '';
  if (!q) {{ searchRes.style.display='none'; return; }}

  const matches = ENTITIES.filter(e =>
    e.name.toLowerCase().includes(q) ||
    (e.label||'').toLowerCase().includes(q)
  );

  if (!matches.length) {{
    searchRes.style.display='none'; return;
  }}
  matches.forEach(e => {{
    const item = document.createElement('div');
    item.className = 'sr-item';
    // Highlight de zoekterm in de naam
    const hi = e.name.replace(new RegExp(`(${{q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')}})`, 'gi'),
                              `<span class="sr-highlight">$1</span>`);
    item.innerHTML = hi + (e.label ? ` <span style="color:#8899aa;font-size:10px">${{e.label}}</span>` : '');
    item.addEventListener('click', () => {{
      searchRes.style.display = 'none';
      clearSearchHighlight();
      const el = document.getElementById('ent_'+e.id);
      if (!el) return;
      el.classList.add('search-match');
      // Pan en zoom naar de entiteit
      const ex = pos[e.id].x + el.offsetWidth/2;
      const ey = pos[e.id].y + el.offsetHeight/2;
      sc = 1.1;
      off.x = wrap.clientWidth/2  - ex*sc;
      off.y = wrap.clientHeight/2 - ey*sc;
      applyT(); draw(); drawMinimap();
    }});
    searchRes.appendChild(item);
  }});
  searchRes.style.display = 'block';
}});

searchClr.addEventListener('click', () => {{
  searchEl.value=''; searchClr.style.display='none';
  searchRes.style.display='none'; clearSearchHighlight();
}});

// Sluit zoekresultaten bij klik buiten
document.addEventListener('click', ev => {{
  if (!ev.target.closest('#search-wrap')) searchRes.style.display='none';
}});

// ── Init ───────────────────────────────────────────────────────────────────
pos = loadPos();
ENTITIES.forEach(makeEnt);
off={{x:20,y:10}}; applyT();
setTimeout(() => {{ draw(); drawMinimap(); }}, 120);
</script>
</body>
</html>
"""


def render_erd(model: dict, all_attrs: bool) -> str:
    """Genereer een standalone interactieve ERD HTML pagina."""

    entities   = model['entities']
    model_name = model['model_name']
    positions  = compute_layout(entities)

    # Entiteiten bouwen voor JS
    ent_list = []
    for e in entities:
        attrs_out = []
        for a in e['attributes']:
            if not all_attrs and a['dim_meta']:
                continue
            attrs_out.append({
                'name':  a['name'],
                'dtype': a['datatype'],
                'pk':    a['pk'],
                'sk':    a['surrogate'],
                'meta':  a['dim_meta'],
                'fk':    any(a['name'] in fk['name'] for fk in e['fks']),
                'desc':  a['description'][:150] + ('…' if len(a['description']) > 150 else ''),
            })
        ent_list.append({
            'id':    e['id'],
            'name':  e['name'],
            'label': e['label'],
            'desc':  e['description'][:200] + ('…' if len(e['description']) > 200 else ''),
            'attrs': attrs_out,
        })

    # Relaties bouwen voor JS
    name_to_id = {e['name']: e['id'] for e in entities}
    rels_list  = []
    seen       = set()
    for e in entities:
        for fk in e['fks']:
            pid = name_to_id.get(fk['parent_table'])
            cid = e['id']
            if pid and pid != cid:
                key = (pid, cid)
                if key not in seen:
                    seen.add(key)
                    rels_list.append({
                        'p':  pid,
                        'c':  cid,
                        'i':  fk['identifying'],
                        'lp': fk['parent_table'],   # labelnaam parent
                        'lc': e['name'],             # labelnaam child
                    })

    pos_by_id = {
        name_to_id[name]: xy
        for name, xy in positions.items()
        if name in name_to_id
    }

    # Unieke sleutel voor localStorage (op basis van modelnaam)
    import hashlib
    model_key = hashlib.md5(model_name.encode()).hexdigest()[:12]

    init_mode = 'all' if all_attrs else 'keys'

    html = ERD_TEMPLATE.format(
        model_name       = model_name,
        model_key        = model_key,
        init_mode        = init_mode,
        mode_none_active = 'active' if init_mode == 'none' else '',
        mode_keys_active = 'active' if init_mode == 'keys' else '',
        mode_all_active  = 'active' if init_mode == 'all'  else '',
        entities_json   = json.dumps(ent_list,  ensure_ascii=False),
        rels_json       = json.dumps(rels_list, ensure_ascii=False),
        positions_json  = json.dumps(pos_by_id, ensure_ascii=False),
    )
    return html


# ---------------------------------------------------------------------------
# Markdown renderen (ongewijzigd)
# ---------------------------------------------------------------------------
def render_markdown(model: dict) -> str:
    lines = []
    ts = datetime.now().strftime('%d-%m-%Y %H:%M')

    lines.append(f"# {model['model_name']} — Logisch Datamodel\n")
    lines.append(f"*Gegenereerd op {ts} door ldm_convert.py*\n")

    mi = model['model_info']
    if mi:
        lines.append("## Modelinformatie\n")
        lines.append("| Eigenschap | Waarde |")
        lines.append("|---|---|")
        for k, v in mi.items():
            lines.append(f"| {k} | {escape_md(v)} |")
        lines.append("")

    lines.append("## Inhoudsopgave\n")
    for e in model['entities']:
        anchor = make_anchor(e['name'])
        label  = f" `{e['label']}`" if e['label'] else ''
        lines.append(f"- [{e['name']}](#{anchor}){label}")
    lines.append("")

    lines.append("---\n")

    for e in model['entities']:
        anchor = make_anchor(e['name'])
        lines.append(f'<a name="{anchor}"></a>')
        lines.append(f"## {e['name']}\n")

        if e['label']:
            lines.append(f"**Fysieke tabelnaam:** `{e['label']}`\n")

        if e['description']:
            lines.append(f"> {escape_md(e['description'])}\n")
        else:
            lines.append("> *Geen beschrijving beschikbaar.*\n")

        func_attrs = [a for a in e['attributes'] if not a['dim_meta']]
        meta_attrs = [a for a in e['attributes'] if a['dim_meta']]

        if func_attrs:
            lines.append("### Attributen\n")
            lines.append("| Naam | Datatype | PK | Verplicht | Surrogate | Beschrijving |")
            lines.append("|---|---|:---:|:---:|:---:|---|")
            for a in func_attrs:
                desc = escape_md(a['description'][:120] + ('…' if len(a['description']) > 120 else ''))
                lines.append(
                    f"| **{escape_md(a['name'])}** | `{a['datatype']}` "
                    f"| {'✓' if a['pk'] else ''} "
                    f"| {'✓' if a['required'] else ''} "
                    f"| {'✓' if a['surrogate'] else ''} "
                    f"| {desc} |"
                )
            lines.append("")

        if meta_attrs:
            lines.append("<details>")
            lines.append("<summary>DIM / bitemporale metadata-velden</summary>\n")
            lines.append("| Naam | Datatype | Verplicht |")
            lines.append("|---|---|:---:|")
            for a in meta_attrs:
                lines.append(
                    f"| {escape_md(a['name'])} | `{a['datatype']}` "
                    f"| {'✓' if a['required'] else ''} |"
                )
            lines.append("")
            lines.append("</details>\n")

        if e['pk_attrs']:
            lines.append("### Primary Key\n")
            lines.append(', '.join(f'`{k}`' for k in e['pk_attrs']) + '\n')

        if e['fks']:
            lines.append("### Foreign Keys\n")
            lines.append("| Relatie | Parent tabel | Multipliciteit | Identifying |")
            lines.append("|---|---|---|:---:|")
            for fk in e['fks']:
                lines.append(
                    f"| {escape_md(fk['name'])} "
                    f"| **{escape_md(fk['parent_table'])}** "
                    f"| {multiplicity_label(fk['child_mult'], fk['parent_mult'])} "
                    f"| {'✓' if fk['identifying'] else ''} |"
                )
            lines.append("")

        lines.append("---\n")

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Statistieken loggen
# ---------------------------------------------------------------------------
def log_stats(model: dict, xml_path: Path, md_path: Path | None, erd_path: Path | None) -> None:
    s = model['stats']
    log.info("─" * 60)
    log.info("Conversie geslaagd: %s", xml_path.name)
    log.info("  Model naam        : %s", model['model_name'])
    log.info("  Entiteiten        : %d", s['entities'])
    log.info("  Attributen totaal : %d  (waarvan %d DIM-meta)", s['total_attributes'], s['dim_meta_attributes'])
    log.info("  Foreign keys      : %d", s['foreign_keys'])
    if md_path:
        log.info("  Markdown output   : %s (%d bytes)", md_path.name, md_path.stat().st_size)
        html_path = md_path.with_suffix('.html')
        if html_path.exists():
            log.info("  HTML output       : %s (%d bytes)", html_path.name, html_path.stat().st_size)
    if erd_path:
        log.info("  ERD output        : %s (%d bytes)", erd_path.name, erd_path.stat().st_size)
    if s['entities_without_description']:
        log.warning("  Entiteiten zonder beschrijving (%d): %s",
                    len(s['entities_without_description']),
                    ', '.join(s['entities_without_description']))
    log.info("─" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("=" * 60)
    log.info("LDM XML → Markdown + ERD converter gestart")
    log.info("  Attribuutmodus : alle attributen (incl. DIM-meta)")
    log.info("  Markdown       : ja")
    log.info("  ERD            : ja")

    xml_path = find_xml_file()

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        log.error("XML parsefout in %s: %s", xml_path.name, exc)
        sys.exit(1)

    validate_ldm(root, xml_path)
    model = parse_model(root)

    safe_name = model['model_name'].replace(' ', '_').replace('/', '-')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    md_path  = OUTPUT_DIR / f"{safe_name}_Datamodel.md"
    md_text  = render_markdown(model)
    md_path.write_text(md_text, encoding='utf-8')

    html_path = OUTPUT_DIR / f"{safe_name}_Datamodel.html"
    html_path.write_text(
        _md_to_html(md_text, title=f"{model['model_name']} — Datamodel"),
        encoding='utf-8'
    )

    erd_path = OUTPUT_DIR / f"{safe_name}_ERD.html"
    erd_path.write_text(render_erd(model, all_attrs=True), encoding='utf-8')

    log_stats(model, xml_path, md_path, erd_path)


if __name__ == '__main__':
    main()
