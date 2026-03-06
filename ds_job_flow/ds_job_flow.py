#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""IBM DataStage DSExport XML (single job) → interactieve dataflow HTML

Genereert een standalone HTML met een interactieve dataflow-diagram van één parallel job.
Stages worden gepositioneerd op basis van de originele XY-coördinaten uit het XML.
Klik op een stage om SQL, tabelinformatie en kolomdefinities te zien.

Gebruik: leg één DSExport XML in de map en draai `python3 ds_job_flow.py`
Output : <jobname>_JobFlow.html  +  ds_job_flow.log
"""

import re, html as htmllib, sys, logging, json, xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'ds_job_flow.log'

log = logging.getLogger(__name__)

WM_LABEL   = {'0': 'INSERT', '1': 'UPDATE', '6': 'BULK LOAD', '9': 'UPSERT/MERGE'}
SKIP_LABEL = {'0': 'Geen',  '1': 'Uniek',  '2': 'Alles'}

# Mapping technische stage-types → leesbare naam
STAGE_TYPE_LABEL = {
    'OracleConnectorPX': 'Oracle Connector',
    'PxAggregator':      'Aggregator',
    'PxJoin':            'Join',
    'PxModify':          'Modify',
    'PxSequentialFile':  'Sequential File',
    'TransformerStage':  'Transformer',
    'CTransformerStage': 'Transformer',
    'PxSVTransformer':   'SV Transformer',
    'PxFilter':          'Filter',
    'PxFunnel':          'Funnel',
    'PxSort':            'Sort',
    'PxPeek':            'Peek',
    'PxHead':            'Head',
    'PxSample':          'Sample',
    'PxLookup':          'Lookup',
    'PxMerge':           'Merge',
    'PxSurrogateKey':    'Surrogate Key',
    'PxChangeCapture':   'Change Capture',
    'PxColumnImport':    'Column Import',
    'PxColumnExport':    'Column Export',
    'PxRowSplitter':     'Row Splitter',
    'PxRowMerger':       'Row Merger',
    'PxDifference':      'Difference',
    'PxIntersection':    'Intersection',
    'CustomStage':       'Custom',
}

def stage_type_label(raw_type):
    if raw_type in STAGE_TYPE_LABEL:
        return STAGE_TYPE_LABEL[raw_type]
    for k, v in STAGE_TYPE_LABEL.items():
        if k in raw_type:
            return v
    return raw_type

def parse_ds_list(val):
    """Parse DataStage \\(N)-encoded list naar lijst van veld-lijsten."""
    rows = val.split('\\(1)')
    result = []
    for row in rows:
        row = row.lstrip('\\(2)').lstrip('\\(3)')
        fields = row.split('\\(2)')
        fields = [f.lstrip('\\(3)') for f in fields if f]
        if len(fields) >= 2:
            result.append(fields)
    return result

def parse_join_props(body):
    """Haal join type en join keys op uit CustomProperty SubRecords."""
    props = {}
    for sr in re.findall(r'<SubRecord>(.*?)</SubRecord>', body, re.DOTALL):
        n = prop(sr, 'Name')
        v = prop(sr, 'Value')
        if n:
            props[n] = v
    operator = props.get('operator', 'join')
    key_val  = props.get('key', '')
    keys = [r[1] for r in parse_ds_list(key_val) if r[0] == 'key' and len(r) > 1]
    return {'operator': operator, 'keys': keys}

def parse_agg_props(body):
    """Haal aggregatie methode, groepeersleutels en reduce-functies op."""
    props = {}
    for sr in re.findall(r'<SubRecord>(.*?)</SubRecord>', body, re.DOTALL):
        n = prop(sr, 'Name')
        v = prop(sr, 'Value')
        if n:
            props[n] = v
    method  = props.get('method', 'sort')
    key_val = props.get('key', '')
    keys    = [r[1] for r in parse_ds_list(key_val) if r[0] == 'key' and len(r) > 1]
    # reduce: rijen met type 'reduce' bevatten kolomnaam; volgende rij bevat de functie
    aggs    = []
    rows    = parse_ds_list(props.get('reduce', ''))
    i = 0
    while i < len(rows):
        row = rows[i]
        if row[0] == 'reduce' and len(row) > 1:
            col  = row[1]
            func = ''
            # volgende rij is de aggregatiefunctie
            if i + 1 < len(rows) and rows[i+1][0] not in ('reduce', 'preserveType'):
                func = rows[i+1][0]
                i += 1
            if col:
                aggs.append({'col': col, 'func': func})
        i += 1
    return {'method': method, 'keys': keys, 'aggregations': aggs}

# ── Bestand vinden ─────────────────────────────────────────────────────────────

def find_xml_file():
    files = list((ROOT_DIR / 'input').glob('*.xml'))
    if len(files) == 0:
        log.error('Geen XML-bestand gevonden in input/')
        sys.exit(1)
    if len(files) > 1:
        log.error('Meer dan 1 XML-bestand gevonden: %s', ', '.join(f.name for f in files))
        sys.exit(1)
    return files[0]

def read_xml(path):
    raw = path.read_bytes()
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', errors='replace')

# ── XML helpers ────────────────────────────────────────────────────────────────

def prop(body, name):
    m = re.search(rf'<Property Name="{name}"[^>]*>(.*?)</Property>', body, re.DOTALL)
    if not m:
        return ''
    return re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', m.group(1), flags=re.DOTALL).strip()

def get_xmltree(body):
    srs = re.findall(r'<SubRecord>(.*?)</SubRecord>', body, re.DOTALL)
    for sr in srs:
        n = re.search(r'<Property Name="Name">(.*?)</Property>', sr)
        if n and n.group(1) == 'XMLProperties':
            v = re.search(r'<Property Name="Value"[^>]*>(.*?)</Property>', sr, re.DOTALL)
            if v:
                try:
                    return ET.fromstring(htmllib.unescape(v.group(1).strip()))
                except Exception:
                    pass
    return None

def xprop(tree, *tags):
    for tag in tags:
        el = tree.find(f'.//{tag}')
        if el is not None:
            val = (el.text or '').strip()
            if val:
                return val
    return ''

def xprop_bool(tree, tag):
    """Geeft True als de tag aanwezig is en waarde '1' heeft."""
    el = tree.find(f'.//{tag}')
    if el is not None:
        return (el.text or '').strip() == '1'
    return False

# ── Parsen ─────────────────────────────────────────────────────────────────────

def parse_job(content):
    # Alle records
    records = {}
    for m in re.finditer(
        r'<Record Identifier="([^"]+)" Type="([^"]+)"[^>]*>(.*?)</Record>',
        content, re.DOTALL
    ):
        records[m.group(1)] = (m.group(2), m.group(3))

    if 'ROOT' not in records:
        log.error('Geen ROOT record gevonden — is dit een geldig DSExport XML?')
        sys.exit(1)

    # Job metadata
    root_body = records['ROOT'][1]
    job_name  = prop(root_body, 'Name')
    job_desc  = htmllib.unescape(prop(root_body, 'Description'))

    # Parameters
    params = []
    for sr in re.findall(r'<SubRecord>(.*?)</SubRecord>', root_body, re.DOTALL):
        pname    = prop(sr, 'Name')
        pprompt  = prop(sr, 'Prompt')
        pdefault = prop(sr, 'Default')
        if pname and not pname.startswith('$'):
            params.append({'name': pname, 'prompt': pprompt, 'default': pdefault})

    # ContainerView
    if 'V0' not in records:
        log.error('Geen ContainerView (V0) record gevonden')
        sys.exit(1)
    cv_body = records['V0'][1]

    def split_cv(name):
        return prop(cv_body, name).split('|')

    stage_ids   = split_cv('StageList')
    stage_names = split_cv('StageNames')
    stage_types = split_cv('StageTypeIDs')
    link_names  = split_cv('LinkNames')
    target_ids  = split_cv('TargetStageIDs')
    src_pins    = split_cv('LinkSourcePinIDs')
    xs    = [int(x) for x in split_cv('StageXPos')]
    ys    = [int(y) for y in split_cv('StageYPos')]
    xsizes = split_cv('StageXSize')
    ysizes = split_cv('StageYSize')

    # Stages opbouwen uit ContainerView
    stages = {}
    for i, sid in enumerate(stage_ids):
        name  = stage_names[i].strip() if i < len(stage_names) else ''
        stype = stage_types[i].strip()  if i < len(stage_types) else ''
        if not name or name in ('', ' ') or name.startswith('\\'):
            continue
        xsize = int(xsizes[i]) if i < len(xsizes) and xsizes[i].strip().lstrip('-').isdigit() else 48
        ysize = int(ysizes[i]) if i < len(ysizes) and ysizes[i].strip().lstrip('-').isdigit() else 48
        stages[sid] = {
            'id': sid, 'name': name, 'type': stype,
            'type_label': stage_type_label(stype),
            'x': xs[i] if i < len(xs) else 0,
            'y': ys[i] if i < len(ys) else 0,
            'xsize': xsize, 'ysize': ysize,
            'sql': '', 'table': '', 'wm': '', 'mode': '',
            'columns': [], 'stage_vars': [],
            'input_link': '', 'output_link': '', 'constraint': '',
            'join_props': None, 'agg_props': None,
            # SOURCE extra
            'where_clause': '', 'array_size': '', 'record_count': '',
            'prefetch_row_count': '', 'prefetch_memory_size': '',
            'partitioned_reads': False,
            # TARGET extra
            'before_sql': '', 'after_sql': '',
            'drop_unmatched': False, 'fail_on_row_error': False,
            # BULK LOAD extra
            'direct_parallelism': '', 'buffer_size': '',
            'skip_indexes': '', 'no_log': False,
            'date_cache_size': '', 'rebuild_indexes': False,
        }

    # Stages verrijken met record-details
    for rid, (rtype, body) in records.items():
        if rid not in stages:
            continue
        s = stages[rid]

        if rtype == 'CustomStage':
            st = prop(body, 'StageType')
            if st == 'PxJoin':
                s['mode']       = 'JOIN'
                s['join_props'] = parse_join_props(body)
            elif st == 'PxAggregator':
                s['mode']      = 'AGGREGATE'
                s['agg_props'] = parse_agg_props(body)
            else:
                mode = 'TARGET' if prop(body, 'InputPins') else 'SOURCE'
                s['mode'] = mode
                tree = get_xmltree(body)
                if tree is not None:
                    s['sql']   = xprop(tree, 'SelectStatement', 'UserDefinedSQL')
                    s['table'] = xprop(tree, 'TableName')
                    wm_raw     = xprop(tree, 'WriteMode')
                    s['wm']    = WM_LABEL.get(wm_raw, wm_raw)

                    if mode == 'SOURCE':
                        where_el = tree.find('.//WhereClause')
                        if where_el is not None and (where_el.text or '').strip():
                            s['where_clause'] = where_el.text.strip()
                        s['array_size']           = xprop(tree, 'ArraySize')
                        s['record_count']         = xprop(tree, 'RecordCount')
                        s['prefetch_row_count']   = xprop(tree, 'PrefetchRowCount')
                        s['prefetch_memory_size'] = xprop(tree, 'PrefetchMemorySize')
                        s['partitioned_reads']    = xprop_bool(tree, 'EnablePartitionedReads')

                    elif mode == 'TARGET':
                        s['array_size']        = xprop(tree, 'ArraySize')
                        s['record_count']      = xprop(tree, 'RecordCount')
                        s['drop_unmatched']    = xprop_bool(tree, 'DropUnmatchedFields')
                        s['fail_on_row_error'] = xprop_bool(tree, 'FailOnRowErrorPX')
                        before_el = tree.find('.//BeforeSQL')
                        if before_el is not None and (before_el.text or '').strip():
                            s['before_sql'] = before_el.text.strip()
                        after_el = tree.find('.//AfterSQL')
                        if after_el is not None and (after_el.text or '').strip():
                            s['after_sql'] = after_el.text.strip()
                        # Bulk Load extra (WriteMode=6)
                        if wm_raw == '6':
                            s['direct_parallelism'] = xprop(tree, 'DirectParallelism')
                            s['buffer_size']        = xprop(tree, 'BufferSize')
                            skip_raw                = xprop(tree, 'SkipIndexes')
                            s['skip_indexes']       = SKIP_LABEL.get(skip_raw, skip_raw)
                            s['no_log']             = xprop_bool(tree, 'NoLog')
                            s['date_cache_size']    = xprop(tree, 'DateCacheSize')
                            s['rebuild_indexes']    = xprop_bool(tree, 'RebuildIndexes')

        elif rtype == 'TransformerStage':
            s['mode'] = 'TRANSFORM'
            # Stage vars (aparte StageVar records)
            for sv_m in re.finditer(r'<Record[^>]+Type="StageVar"[^>]*>(.*?)</Record>', body, re.DOTALL):
                svb = sv_m.group(1)
                svn = prop(svb, 'Name')
                svd = prop(svb, 'Derivation')
                if svn:
                    s['stage_vars'].append({
                        'name': svn,
                        'derivation': htmllib.unescape(svd).replace('\r\n',' ').replace('\n',' ').strip() if svd else '',
                    })
            s['input_link'] = ''  # wordt ingevuld via TrxInput records

    # TrxInput: input link naam koppelen aan transformer
    SKIP_COLS = {'DiskWriteInc', 'BufFreeRun', 'MaxMemBufSize', 'QueueUpperSize', 'Schema'}
    # Pin → stage map voor TrxInput/Output koppeling
    pin_to_stage = {}
    for sid, s in stages.items():
        for ptype in ('InputPins', 'OutputPins'):
            body = records.get(sid, ('',''))[1]
            for pin in prop(body, ptype).split('|'):
                pin = pin.strip()
                if pin:
                    pin_to_stage[pin] = sid

    # TrxInput records: geef transformer zijn input link naam
    for rid, (rtype, body) in records.items():
        if rtype != 'TrxInput':
            continue
        link_nm = prop(body, 'Name')
        # Zoek de bijbehorende transformer via InputPins
        for sid, s in stages.items():
            if s.get('mode') != 'TRANSFORM':
                continue
            tbody = records.get(sid, ('',''))[1]
            in_pins = prop(tbody, 'InputPins')
            # TrxInput identifier bevat stage-prefix
            if rid.startswith(sid) or link_nm == prop(tbody, 'InputPins'):
                s['input_link'] = link_nm
                break

    # TrxOutput records: kolommen (SubRecords) + constraint koppelen aan transformer
    for rid, (rtype, body) in records.items():
        if rtype != 'TrxOutput':
            continue
        link_nm   = prop(body, 'Name')
        constraint_raw = prop(body, 'Constraint')
        constraint = htmllib.unescape(constraint_raw).replace('\r\n', ' ').replace('\n', ' ').strip() if constraint_raw else ''

        cols = []
        for sr in re.findall(r'<SubRecord>(.*?)</SubRecord>', body, re.DOTALL):
            cname = prop(sr, 'Name')
            if not cname or cname in SKIP_COLS:
                continue
            deriv_raw = prop(sr, 'Derivation')
            deriv = htmllib.unescape(deriv_raw).replace('\r\n', ' ').replace('\n', ' ').strip() if deriv_raw else ''
            sqltype = prop(sr, 'SqlType') or prop(sr, 'Category') or ''
            cols.append({'name': cname, 'type': sqltype, 'deriv': deriv})

        # Koppel aan transformer via stage-ID prefix op het TrxOutput record-ID
        for sid, s in stages.items():
            if s.get('mode') != 'TRANSFORM':
                continue
            if rid.startswith(sid):
                s['columns']    = cols
                s['constraint'] = constraint
                s['output_link'] = link_nm
                break

    # (mode override voor JOIN/AGGREGATE zit nu in CustomStage parsing)

    # Links
    links = []
    for i, lname in enumerate(link_names):
        if not lname or lname.strip() in ('', ' ') or lname.startswith('\\'):
            continue
        tgt      = target_ids[i].strip() if i < len(target_ids) else ''
        src_pin  = src_pins[i].strip()   if i < len(src_pins) else ''
        src      = re.sub(r'P\d+$', '', src_pin)
        if src in stages and tgt in stages:
            links.append({'name': lname.strip(), 'src': src, 'tgt': tgt})

    # Annotaties
    annotations = []
    for i, sid in enumerate(stage_ids):
        if sid not in records:
            continue
        rtype, body = records[sid]
        if rtype == 'Annotation' and prop(body, 'AnnotationType') == '0':
            txt = prop(body, 'AnnotationText').strip()
            if txt:
                xsize = int(xsizes[i]) if i < len(xsizes) and xsizes[i].strip().lstrip('-').isdigit() else 200
                ysize = int(ysizes[i]) if i < len(ysizes) and ysizes[i].strip().lstrip('-').isdigit() else 60
                annotations.append({
                    'text': txt,
                    'x': xs[i] if i < len(xs) else 0,
                    'y': ys[i] if i < len(ys) else 0,
                    'w': xsize, 'h': ysize,
                })

    return {
        'job': job_name,
        'description': job_desc,
        'params': params,
        'stages': list(stages.values()),
        'links': links,
        'annotations': annotations,
    }

# ── HTML genereren ─────────────────────────────────────────────────────────────

_TEMPLATE = (SCRIPT_DIR / 'job_flow_template.html').read_text(encoding='utf-8')


def build_html(data, export_date, source_file):
    title_esc   = htmllib.escape(data['job'])
    source_esc  = htmllib.escape(source_file)
    stage_count = len(data['stages'])
    link_count  = len(data['links'])
    src_count   = sum(1 for s in data['stages'] if s['mode'] == 'SOURCE')
    tgt_count   = sum(1 for s in data['stages'] if s['mode'] == 'TARGET')
    return (
        _TEMPLATE
        .replace('{TITLE}',         title_esc)
        .replace('{SOURCE_FILE}',   source_esc)
        .replace('{EXPORT_DATE}',   htmllib.escape(export_date))
        .replace('{STAGE_COUNT}',   str(stage_count))
        .replace('{SRC_COUNT}',     str(src_count))
        .replace('{TGT_COUNT}',     str(tgt_count))
        .replace('{LINK_COUNT}',    str(link_count))
        .replace('{JOB_DATA_JSON}', json.dumps(data, ensure_ascii=False))
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
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


def _main():
    log.info('=' * 60)
    log.info('DataStage XML → Job Flow gestart')

    xml_path = find_xml_file()
    log.info('Input: %s', xml_path.name)

    content = read_xml(xml_path)

    # Exportdatum
    hm = re.search(r'<Header[^>]+Date="([^"]+)"', content)
    export_date = hm.group(1) if hm else '?'
    log.info('Export datum: %s', export_date)

    # Validatie: is dit een DSExport?
    if '<DSExport>' not in content:
        log.error('Geen <DSExport> root element — verwacht een IBM DataStage DSExport XML')
        sys.exit(1)

    data = parse_job(content)

    log.info('Job      : %s', data['job'])
    log.info('Stages   : %d', len(data['stages']))
    log.info('Links    : %d', len(data['links']))
    log.info('Annotaties: %d', len(data['annotations']))
    for s in data['stages']:
        log.info('  %-45s [%s] %s', s['name'], s['mode'], s['type_label'])

    html_out    = build_html(data, export_date, xml_path.name)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{data['job']}_JobFlow.html"
    output_path.write_text(html_out, encoding='utf-8')

    log.info('─' * 60)
    log.info('Output: %s', output_path.name)
    log.info('Bestandsgrootte: %d bytes', output_path.stat().st_size)
    log.info('─' * 60)


if __name__ == '__main__':
    main()
