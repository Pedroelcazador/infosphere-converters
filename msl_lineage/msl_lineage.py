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
import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET

# Importeer parse-logica uit msl_convert via importlib (geen sys.path mutatie)
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
OUTPUT_DIR = ROOT_DIR / 'output'

try:
    _mc_path = ROOT_DIR / 'msl_convert' / 'msl_convert.py'
    _mc_spec = importlib.util.spec_from_file_location('msl_convert', _mc_path)
    _mc      = importlib.util.module_from_spec(_mc_spec)
    sys.modules['msl_convert'] = _mc
    _mc_spec.loader.exec_module(_mc)
    find_msl_file = _mc.find_msl_file
    validate_msl  = _mc.validate_msl
    parse_msl     = _mc.parse_msl
    LOG_FILE      = _mc.LOG_FILE
except Exception as e:
    print(f"Fout bij laden van msl_convert: {e}")
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
_TEMPLATE = (SCRIPT_DIR / 'lineage_template.html').read_text(encoding='utf-8')



def render_lineage(data: dict, title: str) -> str:
    ld = build_lineage_data(data)
    meta = {
        'source_location': ld['source_location'],
        'target_location': ld['target_location'],
    }
    return (
        _TEMPLATE
        .replace('{title}',        title)
        .replace('{sources_json}', json.dumps(ld['sources'], ensure_ascii=False))
        .replace('{targets_json}', json.dumps(ld['targets'], ensure_ascii=False))
        .replace('{meta_json}',    json.dumps(meta,           ensure_ascii=False))
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
