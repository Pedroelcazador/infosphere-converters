#!/usr/bin/env python3
# Versie: 2026-03-05 12:00
"""
IBM InfoSphere Data Architect — DBM XML → Markdown + interactieve ERD (HTML)

Gebruik:
  python dbm_convert.py

Logica:
  - 0 of >1 XML bestanden in input/ → fout in logbestand
  - XML is geen DBM export → fout in logbestand
  - Succesvol → <modelnaam>_Datamodel.md, .html en _ERD.html in output/
"""

import sys
import re
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'dbm_convert.log'

sys.path.insert(0, str(ROOT_DIR))
from md_to_html import md_to_html as _md_to_html

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------
def get_prop(element, name: str, default: str = '') -> str:
    p = element.find(f'properties/property[@name="{name}"]')
    if p is not None:
        return (p.get('value') or '').strip().replace('\r\n', ' ').replace('\n', ' ')
    return default


def escape_md(text: str) -> str:
    return text.replace('|', '\\|').replace('\n', ' ').strip()


def make_anchor(text: str) -> str:
    return re.sub(r'[^a-z0-9\-]', '', text.lower().replace(' ', '-').replace('_', '-'))


# ---------------------------------------------------------------------------
# Validatie
# ---------------------------------------------------------------------------
def find_xml_file() -> Path:
    xml_files = list(INPUT_DIR.glob('*.xml'))
    if len(xml_files) == 0:
        log.error("Geen XML bestand gevonden in %s", INPUT_DIR)
        log.error("Leg één IBM Data Architect DBM XML bestand in de input/ map en probeer opnieuw.")
        sys.exit(1)
    if len(xml_files) > 1:
        names = ', '.join(f.name for f in xml_files)
        log.error("Meer dan één XML bestand gevonden: %s", names)
        log.error("Zorg dat er precies één XML bestand in de input/ map staat.")
        sys.exit(1)
    log.info("XML bestand gevonden: %s", xml_files[0].name)
    return xml_files[0]


def validate_dbm(root: ET.Element, xml_path: Path) -> None:
    errors = []
    if root.tag != 'database':
        errors.append(
            f"Root element is '{root.tag}', verwacht 'database'. "
            "Dit lijkt geen IBM Data Architect DBM export te zijn."
        )
    schemas = root.findall('databaseElement[@type="Schema"]')
    tables  = [t for s in schemas for t in s.findall('databaseElement[@type="Table"]')]
    if not schemas and not tables:
        errors.append("Geen Schema- of Table-elementen gevonden. "
                      "Dit is mogelijk een ander XML formaat.")
    if errors:
        for err in errors:
            log.error("Validatiefout: %s", err)
        log.error("Conversie afgebroken voor bestand: %s", xml_path.name)
        sys.exit(1)
    log.info("Validatie geslaagd — %d schema('s), %d tabel(len) gevonden",
             len(schemas), len(tables))


# ---------------------------------------------------------------------------
# Parseren
# ---------------------------------------------------------------------------
def parse_model(root: ET.Element) -> dict:
    model_info = {}
    mi = root.find('.//modelElement[@type="Model Information"]')
    if mi is not None:
        for p in mi.findall('properties/property'):
            model_info[p.get('name')] = p.get('value', '')

    db_props = {}
    db_info = root.find('databaseElement[@type="Database Information"]')
    if db_info is not None:
        for p in db_info.findall('properties/property'):
            db_props[p.get('name')] = p.get('value', '')

    schemas = root.findall('databaseElement[@type="Schema"]')
    tables_out = []
    stats = {
        'schemas': len(schemas),
        'tables': 0,
        'total_columns': 0,
        'pk_columns': 0,
        'tables_without_description': [],
    }

    for schema in schemas:
        schema_name = schema.get('name', '')
        for tbl in schema.findall('databaseElement[@type="Table"]'):
            tbl_name  = tbl.get('name', '')
            tbl_label = get_prop(tbl, 'Label')
            tbl_desc  = get_prop(tbl, 'Description')

            if not tbl_desc:
                stats['tables_without_description'].append(tbl_name)

            columns = []
            for col in tbl.findall('databaseElement[@type="Column"]'):
                col_name  = col.get('name', '')
                col_label = get_prop(col, 'Label')
                col_desc  = get_prop(col, 'Description')
                col_dtype = get_prop(col, 'Data Type')
                col_pk    = get_prop(col, 'Is Primary Key') == 'true'
                col_ident = get_prop(col, 'Is Identity') == 'true'
                col_null  = get_prop(col, 'Is Nullable') != 'false'  # false = verplicht
                col_deflt = get_prop(col, 'Default Value')
                if col_deflt.lower() == 'none':
                    col_deflt = ''

                columns.append({
                    'name':     col_name,
                    'label':    col_label,
                    'datatype': col_dtype,
                    'pk':       col_pk,
                    'identity': col_ident,
                    'nullable': col_null,
                    'default':  col_deflt,
                    'description': col_desc,
                })
                stats['total_columns'] += 1
                if col_pk:
                    stats['pk_columns'] += 1

            tables_out.append({
                'name':        tbl_name,
                'id':          tbl.get('id', tbl_name),
                'schema':      schema_name,
                'label':       tbl_label,
                'description': tbl_desc,
                'columns':     columns,
            })
            stats['tables'] += 1

    return {
        'model_name': root.get('name', 'Onbekend model'),
        'model_info': model_info,
        'db_props':   db_props,
        'tables':     tables_out,
        'stats':      stats,
    }


# ---------------------------------------------------------------------------
# Grid layout berekenen (geen FK-hiërarchie beschikbaar)
# ---------------------------------------------------------------------------
def compute_layout(tables: list) -> dict:
    CARD_W  = 260
    CARD_H  = 180
    H_GAP   = 40
    V_GAP   = 60
    COLS    = 4

    positions = {}
    for i, tbl in enumerate(tables):
        col_idx = i % COLS
        row_idx = i // COLS
        x = 20 + col_idx * (CARD_W + H_GAP)
        y = 20 + row_idx * (CARD_H + V_GAP)
        positions[tbl['id']] = {'x': x, 'y': y}
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

  /* ── Tabellen ── */
  .entity {{
    position:absolute; background:#fff;
    border:2px solid #005b9a; border-radius:6px;
    min-width:230px; max-width:290px;
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

  .attr-row {{
    display:flex; align-items:center; padding:3px 10px; gap:5px;
    font-size:10px; border-bottom:1px solid #e8eff6;
  }}
  .attr-row:last-child {{ border-bottom:none; }}
  .attr-row:hover {{ background:#f0f7ff; }}
  .attr-pk {{ color:#004a80; font-weight:700; }}
  .attr-id {{ color:#005530; font-weight:600; }}
  .attr-normal {{ color:#334455; }}
  .attr-name {{ flex:1; }}
  .attr-type {{ color:#8899aa; font-size:9px; font-family:'Courier New',monospace; white-space:nowrap; }}
  .attr-null {{ color:#cc8800; font-size:8px; margin-left:2px; }}

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
  <h1><strong>{model_name}</strong> — Fysiek Datamodel ERD</h1>
  <div id="attr-mode-group">
    <span>Attrs:</span>
    <button class="mode-btn {mode_none_active}"  onclick="setMode('none')"  title="Alleen tabelnamen, geen kolommen">None</button>
    <button class="mode-btn {mode_keys_active}"  onclick="setMode('keys')"  title="Alleen PK-kolommen">Keys</button>
    <button class="mode-btn {mode_all_active}"   onclick="setMode('all')"   title="Alle kolommen">All</button>
  </div>
  <div id="legend">
    <div class="leg"><span>🔑 PK</span></div>
    <div class="leg"><span>∅ nullable</span></div>
  </div>
  <div id="search-wrap">
    <input id="search" type="text" placeholder="🔍 Zoek tabel…" autocomplete="off">
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
<div id="info-panel">Drag • Klik header voor kolommen • Hover voor omschrijving • Scroll = zoom</div>
<div id="minimap"><canvas id="mm-canvas"></canvas><div id="mm-viewport"></div></div>

<script>
let   ATTR_MODE  = '{init_mode}';
const ENTITIES   = {entities_json};
const INIT_POS   = {positions_json};
const STORAGE_KEY = 'dbm_pos_{model_key}';

let pos      = {{}};
let off      = {{x:0, y:0}}, sc = 0.75;
let panning  = false, ps = {{x:0, y:0}};
let hoveredId = null;

const canvas = document.getElementById('canvas');
const svg    = document.getElementById('lines');
const wrap   = document.getElementById('canvas-wrap');
const tip    = document.getElementById('tooltip');
const mmCvs  = document.getElementById('mm-canvas');
const mmVp   = document.getElementById('mm-viewport');
const mmCtx  = mmCvs.getContext('2d');

function loadPos() {{
  try {{
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {{
      const parsed = JSON.parse(saved);
      if (ENTITIES.every(e => parsed[e.id])) return parsed;
    }}
  }} catch(e) {{}}
  return JSON.parse(JSON.stringify(INIT_POS));
}}

function savePos() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(pos)); }} catch(e) {{}}
}}

function applyT() {{
  canvas.style.transform = `translate(${{off.x}}px,${{off.y}}px) scale(${{sc}})`;
  canvas.style.transformOrigin = '0 0';
}}

// ── Pan & Zoom ──────────────────────────────────────────────────────────────
wrap.addEventListener('mousedown', ev => {{
  if (ev.target !== wrap && ev.target !== canvas && ev.target !== svg) return;
  panning = true; ps = {{x: ev.clientX - off.x, y: ev.clientY - off.y}};
  wrap.style.cursor = 'grabbing';
}});
document.addEventListener('mousemove', ev => {{
  if (!panning) return;
  off.x = ev.clientX - ps.x; off.y = ev.clientY - ps.y;
  applyT(); drawMinimap();
}});
document.addEventListener('mouseup', () => {{ panning = false; wrap.style.cursor = ''; }});
wrap.addEventListener('wheel', ev => {{
  ev.preventDefault();
  const f = ev.deltaY < 0 ? 1.12 : 0.89;
  const rect = wrap.getBoundingClientRect();
  const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
  off.x = mx - (mx - off.x) * f; off.y = my - (my - off.y) * f;
  sc = Math.max(0.15, Math.min(3, sc * f));
  applyT(); drawMinimap();
}}, {{passive: false}});

function resetLayout() {{
  localStorage.removeItem(STORAGE_KEY);
  pos = JSON.parse(JSON.stringify(INIT_POS));
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    if (el) {{ el.style.left = pos[e.id].x + 'px'; el.style.top = pos[e.id].y + 'px'; }}
  }});
  off = {{x:20,y:10}}; sc = 0.75; applyT(); drawMinimap();
}}

function fitView() {{
  let mnx=Infinity,mny=Infinity,mxx=0,mxy=0;
  ENTITIES.forEach(e => {{
    const el = document.getElementById('ent_' + e.id);
    const x = pos[e.id]?.x||0, y = pos[e.id]?.y||0;
    mnx=Math.min(mnx,x); mny=Math.min(mny,y);
    mxx=Math.max(mxx,x+(el?el.offsetWidth:260)); mxy=Math.max(mxy,y+(el?el.offsetHeight:60));
  }});
  const pad=60, w=wrap.clientWidth, h=wrap.clientHeight;
  sc = Math.min((w-pad*2)/(mxx-mnx),(h-pad*2)/(mxy-mny),1.5);
  off.x = pad-mnx*sc+(w-pad*2-(mxx-mnx)*sc)/2;
  off.y = pad-mny*sc+(h-pad*2-(mxy-mny)*sc)/2;
  applyT(); drawMinimap();
}}

// ── Mini-map ───────────────────────────────────────────────────────────────
const MM_W = 180, MM_H = 120;
mmCvs.width = MM_W; mmCvs.height = MM_H;

function drawMinimap() {{
  mmCtx.clearRect(0,0,MM_W,MM_H);
  mmCtx.fillStyle = '#eef2f7'; mmCtx.fillRect(0,0,MM_W,MM_H);
  let mnx=Infinity,mny=Infinity,mxx=0,mxy=0;
  ENTITIES.forEach(e => {{
    const el=document.getElementById('ent_'+e.id);
    const x=pos[e.id]?.x||0, y=pos[e.id]?.y||0;
    const w=el?el.offsetWidth:260, h=el?el.offsetHeight:60;
    mnx=Math.min(mnx,x);mny=Math.min(mny,y);mxx=Math.max(mxx,x+w);mxy=Math.max(mxy,y+h);
  }});
  const pad=10;
  const scx=(MM_W-pad*2)/(mxx-mnx||1), scy=(MM_H-pad*2)/(mxy-mny||1);
  const msc=Math.min(scx,scy);
  ENTITIES.forEach(e => {{
    const el=document.getElementById('ent_'+e.id);
    const x=pad+(pos[e.id].x-mnx)*msc, y=pad+(pos[e.id].y-mny)*msc;
    const w=(el?el.offsetWidth:260)*msc, h=(el?el.offsetHeight:60)*msc;
    mmCtx.fillStyle='#005b9a';
    mmCtx.fillRect(x,y,Math.max(w,3),Math.max(h,3));
  }});
  const vx=pad+(-off.x/sc-mnx)*msc, vy=pad+(-off.y/sc-mny)*msc;
  const vw=wrap.clientWidth/sc*msc, vh=wrap.clientHeight/sc*msc;
  mmVp.style.left=Math.max(0,vx)+'px'; mmVp.style.top=Math.max(0,vy)+'px';
  mmVp.style.width=Math.min(vw,MM_W-Math.max(0,vx))+'px';
  mmVp.style.height=Math.min(vh,MM_H-Math.max(0,vy))+'px';
}}

document.getElementById('minimap').addEventListener('click', ev => {{
  const rect=mmCvs.getBoundingClientRect();
  let mnx=Infinity,mny=Infinity,mxx=0,mxy=0;
  ENTITIES.forEach(e => {{
    const el=document.getElementById('ent_'+e.id);
    const x=pos[e.id]?.x||0,y=pos[e.id]?.y||0;
    const w=el?el.offsetWidth:260, h=el?el.offsetHeight:60;
    mnx=Math.min(mnx,x);mny=Math.min(mny,y);mxx=Math.max(mxx,x+w);mxy=Math.max(mxy,y+h);
  }});
  const pad=10,msc=Math.min((MM_W-pad*2)/(mxx-mnx||1),(MM_H-pad*2)/(mxy-mny||1));
  const cx=(ev.clientX-rect.left-pad)/msc+mnx, cy=(ev.clientY-rect.top-pad)/msc+mny;
  off.x=wrap.clientWidth/2-cx*sc; off.y=wrap.clientHeight/2-cy*sc;
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
  const q=searchEl.value.trim().toLowerCase();
  searchClr.style.display=q?'block':'none';
  clearSearchHighlight(); searchRes.innerHTML='';
  if (!q) {{ searchRes.style.display='none'; return; }}
  const matches=ENTITIES.filter(e=>e.name.toLowerCase().includes(q)||(e.label||'').toLowerCase().includes(q));
  if (!matches.length) {{ searchRes.style.display='none'; return; }}
  matches.forEach(e => {{
    const item=document.createElement('div'); item.className='sr-item';
    const hi=e.name.replace(new RegExp(`(${{q.replace(/[.*+?^${{}}()|[\]\\]/g,'\\$&')}})`, 'gi'),
                            `<span class="sr-highlight">$1</span>`);
    item.innerHTML=hi+(e.label?` <span style="color:#8899aa;font-size:10px">${{e.label}}</span>`:'');
    item.addEventListener('click', () => {{
      searchRes.style.display='none'; clearSearchHighlight();
      const el=document.getElementById('ent_'+e.id); if (!el) return;
      el.classList.add('search-match');
      const ex=pos[e.id].x+el.offsetWidth/2, ey=pos[e.id].y+el.offsetHeight/2;
      sc=1.1; off.x=wrap.clientWidth/2-ex*sc; off.y=wrap.clientHeight/2-ey*sc;
      applyT(); drawMinimap();
    }});
    searchRes.appendChild(item);
  }});
  searchRes.style.display='block';
}});
searchClr.addEventListener('click',()=>{{ searchEl.value=''; searchClr.style.display='none'; searchRes.style.display='none'; clearSearchHighlight(); }});
document.addEventListener('click',ev=>{{ if (!ev.target.closest('#search-wrap')) searchRes.style.display='none'; }});

// ── Tabel aanmaken ─────────────────────────────────────────────────────────
function makeEnt(e) {{
  const el=document.createElement('div'); el.className='entity'; el.id='ent_'+e.id;
  el.style.left=pos[e.id].x+'px'; el.style.top=pos[e.id].y+'px';

  const hdr=document.createElement('div'); hdr.className='entity-header';
  hdr.innerHTML=`<div class="entity-name">${{e.name}}</div>`
               +(e.schema?`<div class="entity-label">${{e.schema}}</div>`:'');
  if (e.desc) {{ hdr.addEventListener('mousemove',ev=>showTip(ev,e.desc)); hdr.addEventListener('mouseleave',hideTip); }}
  el.appendChild(hdr);

  const ad=document.createElement('div'); ad.className='entity-attrs'; ad.dataset.entId=e.id;
  renderAttrs(ad,e); el.appendChild(ad);

  const tog=document.createElement('div'); tog.className='toggle-btn';
  tog.textContent=ATTR_MODE!=='none'?'▴ verbergen':'▾ kolommen tonen';
  tog.addEventListener('click',()=>{{
    if (ad._expanded) {{
      ad._expanded=false; renderAttrs(ad,e);
      tog.textContent=ad.classList.contains('collapsed')?'▾ kolommen tonen':'▴ verbergen';
    }} else {{
      ad._expanded=true; ad.classList.remove('collapsed');
      while (ad.firstChild) ad.removeChild(ad.firstChild);
      e.attrs.forEach(a=>ad.appendChild(makeAttrRow(a)));
      tog.textContent='▴ verbergen';
    }}
    setTimeout(()=>drawMinimap(),320);
  }});
  el.appendChild(tog);

  drag(el,e.id,hdr);
  canvas.appendChild(el);
}}

function renderAttrs(container,e) {{
  while (container.firstChild) container.removeChild(container.firstChild);
  if (ATTR_MODE==='none') return;
  const visible=e.attrs.filter(a=>ATTR_MODE==='keys'?a.pk:true);
  visible.forEach(a=>container.appendChild(makeAttrRow(a)));
}}

function setMode(mode) {{
  ATTR_MODE=mode;
  document.querySelectorAll('.mode-btn').forEach(btn=>{{
    btn.classList.toggle('active',btn.getAttribute('onclick').includes("'"+mode+"'"));
  }});
  ENTITIES.forEach(e=>{{
    const ad=document.querySelector('.entity-attrs[data-ent-id="'+e.id+'"]');
    if (ad) renderAttrs(ad,e);
  }});
  ENTITIES.forEach(e=>{{
    const el=document.getElementById('ent_'+e.id);
    const ad=el?.querySelector('.entity-attrs'), tog=el?.querySelector('.toggle-btn');
    if (!el||!ad||!tog) return;
    ad._expanded=false;
    if (mode==='none') {{ ad.classList.add('collapsed'); tog.textContent='▾ kolommen tonen'; }}
    else {{ ad.classList.remove('collapsed'); tog.textContent='▴ verbergen'; }}
  }});
  setTimeout(()=>drawMinimap(),50);
}}

function makeAttrRow(a) {{
  const row=document.createElement('div'); row.className='attr-row';
  const icon=a.pk?'🔑 ':a.identity?'⚙ ':'';
  const cls=a.pk?'attr-pk':a.identity?'attr-id':'attr-normal';
  const nullMark=a.nullable?'<span class="attr-null">∅</span>':'';
  row.innerHTML=`<span class="attr-name ${{cls}}">${{icon}}${{a.name}}</span>`
               +`<span class="attr-type">${{a.dtype}}</span>`+nullMark;
  if (a.desc) {{ row.addEventListener('mousemove',ev=>showTip(ev,a.desc)); row.addEventListener('mouseleave',hideTip); }}
  return row;
}}

// ── Drag ──────────────────────────────────────────────────────────────────
function drag(el,id,handle) {{
  let on=false,sx,sy,ex,ey;
  handle.addEventListener('mousedown',ev=>{{
    ev.preventDefault(); on=true; el.classList.add('dragging');
    sx=ev.clientX; sy=ev.clientY; ex=pos[id].x; ey=pos[id].y;
    document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
  }});
  function mv(ev) {{
    if (!on) return;
    pos[id].x=ex+(ev.clientX-sx)/sc; pos[id].y=ey+(ev.clientY-sy)/sc;
    el.style.left=pos[id].x+'px'; el.style.top=pos[id].y+'px'; drawMinimap();
  }}
  function up() {{ on=false; el.classList.remove('dragging'); document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); savePos(); }}
}}

function showTip(ev,text) {{
  tip.textContent=text; tip.style.display='block';
  tip.style.left=Math.min(ev.clientX+14,window.innerWidth-340)+'px';
  tip.style.top=Math.min(ev.clientY+14,window.innerHeight-80)+'px';
}}
function hideTip() {{ tip.style.display='none'; }}

// ── Init ───────────────────────────────────────────────────────────────────
pos=loadPos();
ENTITIES.forEach(makeEnt);
off={{x:20,y:10}}; applyT();
setTimeout(()=>{{drawMinimap();}},120);
</script>
</body>
</html>
"""


def render_erd(model: dict) -> str:
    tables     = model['tables']
    model_name = model['model_name']
    positions  = compute_layout(tables)

    ent_list = []
    for t in tables:
        attrs_out = []
        for c in t['columns']:
            attrs_out.append({
                'name':     c['name'],
                'dtype':    c['datatype'],
                'pk':       c['pk'],
                'identity': c['identity'],
                'nullable': c['nullable'],
                'desc':     c['description'][:150] + ('…' if len(c['description']) > 150 else ''),
            })
        ent_list.append({
            'id':     t['id'],
            'name':   t['name'],
            'schema': t['schema'],
            'label':  t['label'],
            'desc':   t['description'][:200] + ('…' if len(t['description']) > 200 else ''),
            'attrs':  attrs_out,
        })

    pos_by_id = {t['id']: positions[t['id']] for t in tables if t['id'] in positions}
    model_key = hashlib.md5(model_name.encode()).hexdigest()[:12]

    html = ERD_TEMPLATE.format(
        model_name       = model_name,
        model_key        = model_key,
        init_mode        = 'all',
        mode_none_active = '',
        mode_keys_active = '',
        mode_all_active  = 'active',
        entities_json    = json.dumps(ent_list,  ensure_ascii=False),
        positions_json   = json.dumps(pos_by_id, ensure_ascii=False),
    )
    return html


# ---------------------------------------------------------------------------
# Markdown renderen
# ---------------------------------------------------------------------------
def render_markdown(model: dict) -> str:
    lines = []
    ts = datetime.now().strftime('%d-%m-%Y %H:%M')

    lines.append(f"# {model['model_name']} — Fysiek Datamodel\n")
    lines.append(f"*Gegenereerd op {ts} door dbm_convert.py*\n")

    mi = model['model_info']
    if mi:
        lines.append("## Modelinformatie\n")
        lines.append("| Eigenschap | Waarde |")
        lines.append("|---|---|")
        for k, v in mi.items():
            lines.append(f"| {k} | {escape_md(v)} |")
        lines.append("")

    s = model['stats']
    lines.append("## Samenvatting\n")
    lines.append(f"- **Schema's**: {s['schemas']}")
    lines.append(f"- **Tabellen**: {s['tables']}")
    lines.append(f"- **Kolommen totaal**: {s['total_columns']}")
    lines.append(f"- **PK-kolommen**: {s['pk_columns']}")
    lines.append("")

    lines.append("## Inhoudsopgave\n")
    current_schema = None
    for t in model['tables']:
        if t['schema'] != current_schema:
            current_schema = t['schema']
            lines.append(f"\n**Schema: {current_schema}**\n")
        anchor = make_anchor(t['name'])
        label  = f" `{t['label']}`" if t['label'] else ''
        lines.append(f"- [{t['name']}](#{anchor}){label}")
    lines.append("")

    lines.append("---\n")

    for t in model['tables']:
        anchor = make_anchor(t['name'])
        lines.append(f'<a name="{anchor}"></a>')
        lines.append(f"## {t['name']}\n")

        lines.append(f"**Schema:** `{t['schema']}`\n")

        if t['label']:
            lines.append(f"**Label:** {t['label']}\n")

        if t['description']:
            lines.append(f"> {escape_md(t['description'])}\n")
        else:
            lines.append("> *Geen beschrijving beschikbaar.*\n")

        pk_cols = [c['name'] for c in t['columns'] if c['pk']]
        if pk_cols:
            lines.append("**Primary Key:** " + ', '.join(f'`{k}`' for k in pk_cols) + "\n")

        if t['columns']:
            lines.append("### Kolommen\n")
            lines.append("| Naam | Datatype | PK | Nullable | Identity | Beschrijving |")
            lines.append("|---|---|:---:|:---:|:---:|---|")
            for c in t['columns']:
                desc = escape_md(c['description'][:120] + ('…' if len(c['description']) > 120 else ''))
                lines.append(
                    f"| **{escape_md(c['name'])}** | `{c['datatype']}` "
                    f"| {'✓' if c['pk'] else ''} "
                    f"| {'✓' if c['nullable'] else ''} "
                    f"| {'✓' if c['identity'] else ''} "
                    f"| {desc} |"
                )
            lines.append("")

        lines.append("---\n")

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Statistieken loggen
# ---------------------------------------------------------------------------
def log_stats(model: dict, xml_path: Path) -> None:
    s = model['stats']
    log.info("─" * 60)
    log.info("Conversie geslaagd: %s", xml_path.name)
    log.info("  Model naam         : %s", model['model_name'])
    log.info("  Schema's           : %d", s['schemas'])
    log.info("  Tabellen           : %d", s['tables'])
    log.info("  Kolommen totaal    : %d", s['total_columns'])
    if s['tables_without_description']:
        log.warning("  Tabellen zonder beschrijving (%d): %s",
                    len(s['tables_without_description']),
                    ', '.join(s['tables_without_description']))
    log.info("─" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    _fmt = logging.Formatter('%(asctime)s  %(levelname)-8s  %(message)s', '%Y-%m-%d %H:%M:%S')
    _fh  = logging.FileHandler(LOG_FILE, encoding='utf-8')
    _fh.setFormatter(_fmt)
    _sh  = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    log.addHandler(_fh)
    log.addHandler(_sh)
    log.setLevel(logging.INFO)
    try:
        _main()
    finally:
        log.removeHandler(_fh)
        log.removeHandler(_sh)
        _fh.close()


def _main() -> None:
    log.info("=" * 60)
    log.info("DBM XML → Markdown + ERD converter gestart")

    xml_path = find_xml_file()

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        log.error("XML parsefout in %s: %s", xml_path.name, exc)
        sys.exit(1)

    validate_dbm(root, xml_path)
    model = parse_model(root)

    safe_name = model['model_name'].replace(' ', '_').replace('/', '-')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    md_path  = OUTPUT_DIR / f"{safe_name}_Datamodel.md"
    md_text  = render_markdown(model)
    md_path.write_text(md_text, encoding='utf-8')

    html_path = OUTPUT_DIR / f"{safe_name}_Datamodel.html"
    html_path.write_text(
        _md_to_html(md_text, title=f"{model['model_name']} — Fysiek Datamodel"),
        encoding='utf-8'
    )

    erd_path = OUTPUT_DIR / f"{safe_name}_ERD.html"
    erd_path.write_text(render_erd(model), encoding='utf-8')

    log_stats(model, xml_path)
    log.info("Output:")
    log.info("  %s", md_path.name)
    log.info("  %s", html_path.name)
    log.info("  %s", erd_path.name)


if __name__ == '__main__':
    main()
