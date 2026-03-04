#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""
IBM Data Architect — MSL (Mapping Specification Language) → Markdown converter

Gebruik:
  python msl_convert.py
"""

import sys
import re
import logging
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'convert_msl.log'

sys.path.insert(0, str(ROOT_DIR))
from md_to_html import md_to_html, make_anchor

# XML namespace
NS = 'http:///com/ibm/datatools/metadata/mapping/model/model.ecore'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bestand zoeken & valideren
# ---------------------------------------------------------------------------
def find_msl_file() -> Path:
    msl_files = list(INPUT_DIR.glob('*.msl'))

    if len(msl_files) == 0:
        log.error("Geen MSL bestand gevonden in %s", INPUT_DIR)
        log.error("Leg één IBM Data Architect MSL bestand in de input/ map en probeer opnieuw.")
        sys.exit(1)

    if len(msl_files) > 1:
        names = ', '.join(f.name for f in msl_files)
        log.error("Meer dan één MSL bestand gevonden: %s", names)
        log.error("Zorg dat er precies één MSL bestand in de input/ map staat.")
        sys.exit(1)

    log.info("MSL bestand gevonden: %s", msl_files[0].name)
    return msl_files[0]


def validate_msl(root: ET.Element, msl_path: Path) -> None:
    if 'mappingRoot' not in root.tag:
        tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag
        log.error("Validatiefout: root element is '%s', verwacht 'mappingRoot'. "
                  "Dit lijkt geen IBM Data Architect MSL bestand te zijn.", tag)
        log.error("Conversie afgebroken voor: %s", msl_path.name)
        sys.exit(1)

    mappings = root.findall(f'{{{NS}}}mapping')
    if not mappings:
        log.error("Validatiefout: geen mappings gevonden in %s", msl_path.name)
        sys.exit(1)

    log.info("Validatie geslaagd — %d hoofd-mappings gevonden", len(mappings))


# ---------------------------------------------------------------------------
# Resource-detectie
# ---------------------------------------------------------------------------
def detect_resources(root: ET.Element) -> tuple[set[str], set[str]]:
    """
    Bepaal dynamisch welke resource-namen inputs (bronnen) en outputs (doelen) zijn.
    Leest de <msl:inputs name="..."> en <msl:outputs name="..."> elementen.
    Fallback: resource0 = input, resource1 = output.
    """
    input_res  = set()
    output_res = set()

    for el in root.findall(f'{{{NS}}}inputs'):
        name = el.get('name')
        if name:
            input_res.add(f'${name}')

    for el in root.findall(f'{{{NS}}}outputs'):
        name = el.get('name')
        if name:
            output_res.add(f'${name}')

    if not input_res and not output_res:
        # Fallback
        input_res  = {'$_resource0'}
        output_res = {'$_resource1'}

    log.info("Bronresources : %s", ', '.join(sorted(input_res)))
    log.info("Doelresources : %s", ', '.join(sorted(output_res)))
    return input_res, output_res


# ---------------------------------------------------------------------------
# Parseren
# ---------------------------------------------------------------------------
def get_annotation(element: ET.Element) -> str:
    ann = element.find(f'{{{NS}}}annotations[@key="msl_mapping_documentation"]')
    if ann is not None:
        val = ann.get('value', '').strip()
        val = val.replace('\r\n', '\n').replace('\r', '\n').strip()
        return val
    return ''


def strip_path(path: str) -> tuple[str, str, str]:
    """
    '$_resource0/BronTabel/Veld'  → ('$_resource0', 'BronTabel', 'Veld')
    '$_resource0/BronTabel'       → ('$_resource0', 'BronTabel', '')
    """
    parts = path.split('/', 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        return parts[0], parts[1], ''
    return path, '', ''


def classify_mapping(inputs: list[tuple[str, str, str]], has_function: bool) -> str:
    """inputs = [(resource, tabel, veld), ...]"""
    if has_function and not inputs:
        return 'constant'
    if not inputs or len(inputs) == 1:
        return 'direct'

    sources  = [(i[0], i[1]) for i in inputs]   # (resource, tabel)
    fields   = [i[2] for i in inputs]
    unique_s = set(sources)
    unique_f = set(fields)

    if len(unique_s) == 1:
        return 'concat'
    if len(unique_f) == 1:
        return 'join'
    return 'lookup'


def parse_msl(root: ET.Element) -> dict:
    input_res, output_res = detect_resources(root)

    # Bron- en doellocaties uit de resource-elementen
    source_locs = []
    target_locs = []
    for el in root.findall(f'{{{NS}}}inputs'):
        loc = el.get('location', '')
        if loc:
            source_locs.append(loc)
    for el in root.findall(f'{{{NS}}}outputs'):
        loc = el.get('location', '')
        if loc:
            target_locs.append(loc)

    source_location = ', '.join(source_locs) or '?'
    target_location = ', '.join(target_locs) or '?'

    target_mappings = []

    for top_mapping in root.findall(f'{{{NS}}}mapping'):
        # Doeltabel bepalen vanuit de outputs van de top-mapping
        target_table = ''
        for out in top_mapping.findall(f'{{{NS}}}output'):
            res, tbl, field = strip_path(out.get('path', ''))
            if res in output_res:
                if not field:
                    target_table = tbl
                    break
                elif not target_table:
                    target_table = tbl

        if not target_table:
            # Probeer het te bepalen via de geneste mappings
            for nm in top_mapping.findall(f'{{{NS}}}mapping'):
                for out in nm.findall(f'{{{NS}}}output'):
                    res, tbl, field = strip_path(out.get('path', ''))
                    if res in output_res and tbl:
                        target_table = tbl
                        break
                if target_table:
                    break

        if not target_table:
            log.warning("Geen doeltabel gevonden voor mapping id=%s, overgeslagen",
                        top_mapping.get('id', '?'))
            continue

        filter_text = get_annotation(top_mapping)

        # Unieke bronrecords op top-niveau (tabel-paden zonder veld)
        top_sources = []
        for inp in top_mapping.findall(f'{{{NS}}}input'):
            res, tbl, field = strip_path(inp.get('path', ''))
            if res in input_res and not field and tbl not in top_sources:
                top_sources.append(tbl)

        # Attribuutmappings
        attributes = []
        for attr_map in top_mapping.findall(f'{{{NS}}}mapping'):
            notes    = get_annotation(attr_map)
            func_el  = attr_map.find(f'{{{NS}}}function')
            func_val = func_el.get('value', '') if func_el is not None else ''

            inputs = []
            for inp in attr_map.findall(f'{{{NS}}}input'):
                res, tbl, field = strip_path(inp.get('path', ''))
                if res in input_res and field:
                    inputs.append((res, tbl, field))

            target_attr = ''
            for out in attr_map.findall(f'{{{NS}}}output'):
                res, tbl, field = strip_path(out.get('path', ''))
                if res in output_res and field:
                    target_attr = field
                    break

            if not target_attr:
                continue

            mapping_type = classify_mapping(inputs, bool(func_val))

            attributes.append({
                'target':   target_attr,
                'type':     mapping_type,
                'inputs':   inputs,
                'function': func_val,
                'notes':    notes,
            })

        joins = detect_joins(attributes)

        target_mappings.append({
            'target_table': target_table,
            'filter':       filter_text,
            'sources':      top_sources,
            'attributes':   attributes,
            'joins':        joins,
        })

    all_sources = []
    for tm in target_mappings:
        for s in tm['sources']:
            if s not in all_sources:
                all_sources.append(s)

    log.info("Doeltabellen gevonden: %d", len(target_mappings))
    return {
        'source_location': source_location,
        'target_location': target_location,
        'target_mappings': target_mappings,
        'all_sources':     all_sources,
    }


def detect_joins(attributes: list[dict]) -> list[dict]:
    join_pairs: dict[tuple, list[str]] = {}

    for attr in attributes:
        if attr['type'] not in ('join', 'lookup'):
            continue

        inputs   = attr['inputs']
        src_list = list({(i[0], i[1]) for i in inputs})  # unieke (res, tbl) combos

        if len(src_list) < 2:
            continue

        by_src: dict[tuple, list[str]] = {}
        for res, tbl, field in inputs:
            by_src.setdefault((res, tbl), []).append(field)

        all_fields = [set(v) for v in by_src.values()]
        shared = all_fields[0].copy()
        for s in all_fields[1:]:
            shared &= s

        pair = tuple(sorted(f'{r}/{t}' for r, t in src_list))
        if pair not in join_pairs:
            join_pairs[pair] = []
        for f in shared:
            if f not in join_pairs[pair]:
                join_pairs[pair].append(f)

    result = []
    for pair, fields in join_pairs.items():
        result.append({
            'sources': list(pair),
            'fields':  sorted(fields),
        })
    return result


# ---------------------------------------------------------------------------
# Statistieken
# ---------------------------------------------------------------------------
def calc_stats(target_mapping: dict) -> dict:
    attrs = target_mapping['attributes']
    type_counts = {'direct': 0, 'concat': 0, 'join': 0, 'lookup': 0, 'constant': 0}
    with_notes = 0
    for a in attrs:
        type_counts[a['type']] = type_counts.get(a['type'], 0) + 1
        if a['notes']:
            with_notes += 1
    return {
        'total':      len(attrs),
        'types':      type_counts,
        'with_notes': with_notes,
        'sources':    len(target_mapping['sources']),
    }


# ---------------------------------------------------------------------------
# Markdown renderen
# ---------------------------------------------------------------------------
def esc(text: str) -> str:
    return text.replace('|', '\\|').replace('\n', ' ').strip()


def esc_notes(text: str) -> str:
    text = text.replace('|', '\\|').strip()
    lines = [l.rstrip() for l in text.split('\n')]
    result = []
    for line in lines:
        if line:
            result.append(line)
        elif result:
            result.append('<br>')
    while result and result[-1] == '<br>':
        result.pop()
    return '<br>'.join(result)


def format_inputs(inputs: list[tuple[str, str, str]], mapping_type: str, func_val: str) -> str:
    if mapping_type == 'constant':
        return f'`{func_val}`'

    if not inputs:
        return '—'

    if mapping_type == 'direct':
        _, tbl, field = inputs[0]
        return f'{tbl}.{field}'

    if mapping_type == 'concat':
        tbl = inputs[0][1]
        fields = ' + '.join(f'.{f}' for _, _, f in inputs)
        return f'{tbl}{fields}'

    if mapping_type == 'join':
        parts = [f'{tbl}.{field}' for _, tbl, field in inputs]
        return ' / '.join(parts)

    if mapping_type == 'lookup':
        by_src: dict[str, list[str]] = {}
        for _, tbl, field in inputs:
            by_src.setdefault(tbl, []).append(field)
        parts = []
        for tbl, fields in by_src.items():
            if len(fields) == 1:
                parts.append(f'{tbl}.{fields[0]}')
            else:
                parts.append(f'{tbl}.({", ".join(fields)})')
        return ' + '.join(parts)

    return ', '.join(f'{tbl}.{f}' for _, tbl, f in inputs)


def render_markdown(data: dict, msl_path: Path) -> str:
    lines = []
    ts   = datetime.now().strftime('%d-%m-%Y %H:%M')
    stem = msl_path.stem

    mappings = data['target_mappings']

    # Header
    lines.append(f'# {stem} — Attribuutmapping\n')
    lines.append(f'*Gegenereerd op {ts} door msl_convert.py*\n')
    lines.append(f'- **Bron LDM:** `{data["source_location"]}`')
    lines.append(f'- **Doel LDM:** `{data["target_location"]}`\n')
    lines.append('---\n')

    # Inhoudsopgave
    lines.append('## Inhoudsopgave\n')
    for m in mappings:
        anchor = make_anchor(m['target_table'])
        lines.append(f'- [{m["target_table"]}](#{anchor})')
    lines.append('')
    lines.append('---\n')

    # Per doeltabel
    for m in mappings:
        anchor = make_anchor(m['target_table'])
        lines.append(f'<a name="{anchor}"></a>')
        lines.append(f'## {m["target_table"]}\n')

        # Bronnen
        if m['sources']:
            lines.append(f'**Bronnen:** {", ".join(m["sources"])}\n')

        # Filterconditie
        if m['filter']:
            lines.append('### Filterconditie\n')
            for fline in m['filter'].split('\n'):
                if fline.strip():
                    lines.append(f'> {fline.strip()}')
            lines.append('')

        # Attribuutmappings
        attrs = m['attributes']
        if attrs:
            lines.append('### Attribuutmappings\n')
            lines.append('| Doelattribuut | Bron(nen) | Notities |')
            lines.append('|---|---|---|')
            for a in attrs:
                src_str = format_inputs(a['inputs'], a['type'], a['function'])
                notes = esc_notes(a['notes']) if a['notes'] else ''
                lines.append(f'| {esc(a["target"])} | {esc(src_str)} | {notes} |')
            lines.append('')

        # Join-condities
        if m['joins']:
            lines.append('### Join-condities\n')
            lines.append('| Join | Sleutelvelden |')
            lines.append('|---|---|')
            for j in m['joins']:
                srcs = ' = '.join(s.split('/')[-1] for s in j['sources'])
                fields_str = ', '.join(j['fields']) if j['fields'] else '*(zie notities)*'
                lines.append(f'| {srcs} | {fields_str} |')
            lines.append('')

        lines.append('---\n')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Statistieken loggen
# ---------------------------------------------------------------------------
def log_stats(data: dict, msl_path: Path, output_path: Path) -> None:
    total_attrs = sum(len(m['attributes']) for m in data['target_mappings'])
    log.info("─" * 60)
    log.info("Conversie geslaagd: %s → %s", msl_path.name, output_path.name)
    log.info("  Doeltabellen      : %d", len(data['target_mappings']))
    log.info("  Bronrecords       : %d", len(data['all_sources']))
    log.info("  Attribuutmappings : %d totaal", total_attrs)
    for m in data['target_mappings']:
        s = calc_stats(m)
        log.info("    %-35s %d mappings (%d met notities)",
                 m['target_table'], s['total'], s['with_notes'])
    log.info("  Markdown output   : %s (%d bytes)", output_path.name, output_path.stat().st_size)
    html_path = output_path.with_suffix('.html')
    if html_path.exists():
        log.info("  HTML output       : %s (%d bytes)", html_path.name, html_path.stat().st_size)
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
    log.info("MSL → Markdown converter gestart")

    msl_path = find_msl_file()

    try:
        tree = ET.parse(msl_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        log.error("XML parsefout in %s: %s", msl_path.name, exc)
        sys.exit(1)

    validate_msl(root, msl_path)

    data     = parse_msl(root)
    md_text  = render_markdown(data, msl_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{msl_path.stem}_Mapping.md"
    output_path.write_text(md_text, encoding='utf-8')

    html_path = OUTPUT_DIR / f"{msl_path.stem}_Mapping.html"
    html_path.write_text(
        md_to_html(md_text, title=f"{msl_path.stem} — Attribuutmapping"),
        encoding='utf-8'
    )

    log_stats(data, msl_path, output_path)


if __name__ == '__main__':
    main()
