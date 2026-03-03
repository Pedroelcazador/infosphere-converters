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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
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

def build_html(data, export_date, source_file):
    job_data_json = json.dumps(data, ensure_ascii=False)
    title_esc     = htmllib.escape(data['job'])
    source_esc    = htmllib.escape(source_file)
    stage_count   = len(data['stages'])
    link_count    = len(data['links'])
    src_count     = sum(1 for s in data['stages'] if s['mode'] == 'SOURCE')
    tgt_count     = sum(1 for s in data['stages'] if s['mode'] == 'TARGET')

    css = r"""
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --bg:#f4f6f8;--surf:#ffffff;--surf2:#f0f2f5;--border:#d0d7de;
  --text:#1f2328;--muted:#656d76;--accent:#0969da;--accent2:#0550ae;
  --src:#1a7f37;--tgt:#cf222e;--trn:#6e40c9;--join:#953800;--agg:#0550ae;
  --radius:9px;--tbh:52px;--panw:420px;
}
body{
  background:var(--bg);color:var(--text);
  font-family:'Segoe UI',system-ui,sans-serif;
  overflow:hidden;height:100vh;
}

/* ── Toolbar ── */
#toolbar{
  position:fixed;top:0;left:0;right:0;height:var(--tbh);z-index:300;
  background:#fff;border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:0;
  box-shadow:0 1px 3px rgba(0,0,0,.08);
}
#logo{
  width:var(--tbh);height:var(--tbh);background:var(--accent);flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:12px;font-weight:900;color:#fff;
  letter-spacing:-.5px;border-right:1px solid var(--border);
}
#title-block{padding:0 16px;flex:1;min-width:0;}
#job-name{
  font-size:13px;font-weight:700;color:var(--text);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
#job-meta{font-size:11px;color:var(--muted);margin-top:1px;}
#toolbar-right{display:flex;align-items:center;gap:6px;padding:0 12px;flex-shrink:0;}
.tbtn{
  padding:5px 11px;border-radius:6px;
  border:1px solid var(--border);
  background:var(--surf);color:var(--text);
  font-size:11.5px;cursor:pointer;
  transition:background .15s;
}
.tbtn:hover{background:var(--surf2);}
#info-btn{
  padding:5px 10px;border-radius:6px;border:1px solid var(--border);
  background:var(--surf);color:var(--muted);font-size:12px;cursor:pointer;
}
#info-btn:hover{color:var(--accent);}

/* ── Zoekbalk ── */
#search-wrap{
  display:flex;align-items:center;
  border:1px solid var(--border);border-radius:6px;overflow:hidden;
  background:var(--surf);
}
#search-input{
  border:none;outline:none;padding:4px 9px;
  font-size:11.5px;color:var(--text);background:transparent;
  width:160px;
}
#search-clear{
  background:none;border:none;cursor:pointer;
  padding:4px 7px;color:var(--muted);font-size:13px;display:none;
}
#search-clear:hover{color:var(--text);}
#search-count{font-size:10px;color:var(--muted);padding:0 8px 0 2px;white-space:nowrap;}

/* ── Canvas ── */
#canvas-wrap{
  position:fixed;top:var(--tbh);left:0;right:0;bottom:0;
  overflow:hidden;background:var(--bg);
}
#canvas{position:absolute;top:0;left:0;transform-origin:0 0;}

/* ── Stages ── */
.stage{
  position:absolute;
  border-radius:var(--radius);
  border:1.5px solid var(--border);
  background:var(--surf);
  cursor:pointer;
  transition:border-color .15s,box-shadow .12s,transform .1s;
  padding:9px 13px;min-width:160px;max-width:200px;
  box-shadow:0 1px 4px rgba(0,0,0,.1),0 2px 8px rgba(0,0,0,.06);
  user-select:none;
}
.stage:hover{
  border-color:var(--accent);
  transform:translateY(-2px);
  box-shadow:0 0 0 2px rgba(9,105,218,.15),0 4px 14px rgba(0,0,0,.12);
}
.stage.selected{
  border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(9,105,218,.2),0 4px 18px rgba(0,0,0,.14);
}
/* Upstream / downstream highlight bij selectie */
.stage.hl-up{
  border-color:#58a6ff !important;
  box-shadow:0 0 0 2px rgba(88,166,255,.25),0 3px 12px rgba(0,0,0,.1) !important;
}
.stage.hl-down{
  border-color:#f0883e !important;
  box-shadow:0 0 0 2px rgba(240,136,62,.25),0 3px 12px rgba(0,0,0,.1) !important;
}
/* Zoekresultaat dimming */
.stage.dimmed{opacity:.2;pointer-events:none;}
.stage.search-match{
  border-color:var(--accent) !important;
  box-shadow:0 0 0 2px rgba(9,105,218,.3) !important;
}
.stage-badge{
  display:inline-block;
  font-size:9px;font-weight:700;
  padding:2px 6px;border-radius:10px;margin-bottom:6px;
  letter-spacing:.4px;text-transform:uppercase;
}
.badge-SOURCE   {background:#dcfce7;color:#166534;}
.badge-TARGET   {background:#fee2e2;color:#991b1b;}
.badge-TRANSFORM{background:#ede9fe;color:#6d28d9;}
.badge-JOIN     {background:#fef3c7;color:#92400e;}
.badge-AGGREGATE{background:#dbeafe;color:#1d4ed8;}
.stage-name{
  font-size:11px;font-weight:600;color:var(--text);
  line-height:1.3;word-break:break-word;
}

/* ── Annotaties ── */
.annot{
  position:absolute;
  background:#fffbeb;
  border:1px dashed #d0d7de;
  border-radius:6px;
  padding:8px 10px 8px 22px;
  font-size:11px;color:var(--muted);
  line-height:1.5;
  pointer-events:all;
  max-width:280px;
  cursor:grab;
  user-select:none;
}
.annot:active{cursor:grabbing;}
.annot-grip{
  position:absolute;top:5px;left:5px;
  font-size:10px;color:#c0c8d0;
  line-height:1;pointer-events:none;
  letter-spacing:-1px;
}

/* ── Detail panel ── */
#detail-panel{
  position:fixed;top:var(--tbh);right:0;bottom:0;width:var(--panw);
  background:var(--surf);border-left:1px solid var(--border);
  display:none;flex-direction:column;
  z-index:200;
  box-shadow:-2px 0 12px rgba(0,0,0,.08);
}
#detail-panel.open{display:flex;}
#dp-head{
  padding:14px 16px;border-bottom:1px solid var(--border);
  display:flex;align-items:flex-start;gap:10px;flex-shrink:0;
  background:#f6f8fa;
}
#dp-icon{
  width:34px;height:34px;border-radius:8px;
  display:flex;align-items:center;justify-content:center;
  font-size:15px;flex-shrink:0;
}
#dp-title{font-size:13px;font-weight:700;color:var(--text);}
#dp-sub{font-size:10.5px;color:var(--muted);margin-top:2px;}
#dp-close{
  margin-left:auto;background:none;border:1px solid var(--border);
  color:var(--muted);font-size:14px;cursor:pointer;
  padding:2px 6px;border-radius:4px;flex-shrink:0;
}
#dp-close:hover{color:var(--text);background:var(--surf2);}
#dp-body{flex:1;overflow-y:auto;padding:14px 16px;}
#dp-body::-webkit-scrollbar{width:4px;}
#dp-body::-webkit-scrollbar-thumb{background:#d0d7de;border-radius:2px;}

.dp-section{margin-bottom:14px;}
.dp-section-title{
  font-size:10px;font-weight:700;
  color:var(--muted);text-transform:uppercase;letter-spacing:.6px;
  margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid var(--border);
}
.dp-row{display:flex;gap:8px;margin-bottom:4px;align-items:baseline;}
.dp-key{font-size:11px;color:var(--muted);min-width:80px;flex-shrink:0;}
.dp-val{font-size:11px;color:var(--text);word-break:break-word;font-family:'Cascadia Code','Consolas',monospace;}
.dp-val.accent{color:var(--accent);}
.dp-badge{
  display:inline-block;font-size:9px;font-weight:700;
  padding:1px 6px;border-radius:8px;letter-spacing:.3px;
}
.dp-badge.ok{background:#dcfce7;color:#166534;}
.dp-badge.warn{background:#fff3cd;color:#856404;}
.dp-badge.no{background:#f0f2f5;color:#57606a;}

.sql-block{
  background:#f6f8fa;border:1px solid var(--border);
  border-radius:6px;padding:10px 12px;
  font-family:'Cascadia Code','Consolas','Courier New',monospace;
  font-size:10.5px;color:#24292f;
  line-height:1.6;overflow-x:auto;white-space:pre;
  max-height:280px;overflow-y:auto;
}
.sql-block::-webkit-scrollbar{width:4px;height:4px;}
.sql-block::-webkit-scrollbar-thumb{background:#d0d7de;}

/* SQL syntax highlighting */
.kw{color:#0550ae;font-weight:600;}
.fn{color:#6e40c9;}
.st{color:#0a3069;}
.cm{color:#6e7781;font-style:italic;}

.col-table{width:100%;border-collapse:collapse;}
.col-table th{
  font-size:9px;font-weight:700;
  color:var(--muted);text-transform:uppercase;letter-spacing:.5px;
  text-align:left;padding:4px 6px;border-bottom:1px solid var(--border);
  background:#f6f8fa;
}
.col-table td{
  font-family:'Cascadia Code','Consolas',monospace;font-size:10px;color:var(--text);
  padding:4px 6px;border-bottom:1px solid #f0f2f5;vertical-align:top;
}
.col-table tr:hover td{background:#f6f8fa;}
.col-type{color:var(--muted);}
.col-name{font-weight:600;white-space:nowrap;}
.col-deriv{color:#656d76;max-width:180px;word-break:break-word;}
.col-logic{color:#24292f;font-size:9.5px;max-width:220px;word-break:break-word;line-height:1.4;}
.passthrough-grid{
  display:flex;flex-wrap:wrap;gap:4px;
}
.pt-item{
  background:#f0f2f5;border:1px solid var(--border);border-radius:4px;
  padding:3px 7px;font-size:10px;display:flex;flex-direction:column;gap:1px;
  max-width:190px;
}
.pt-name{font-weight:600;color:var(--text);font-family:'Cascadia Code','Consolas',monospace;}
.pt-src{color:var(--muted);font-size:9px;font-family:'Cascadia Code','Consolas',monospace;}
.join-type-badge{
  display:inline-block;background:#dbeafe;color:#1d4ed8;
  border:1px solid #bfdbfe;border-radius:6px;
  padding:4px 12px;font-size:11px;font-weight:700;
}
.key-grid{display:flex;flex-wrap:wrap;gap:4px;}
.key-chip{
  background:#f0f7ff;border:1px solid #bfdbfe;border-radius:4px;
  padding:3px 10px;font-family:'Cascadia Code','Consolas',monospace;
  font-size:10px;color:#1d4ed8;font-weight:600;
}
.key-chip-grp{background:#f0fdf4;border-color:#bbf7d0;color:#166534;}
.fn-badge{
  font-family:'Cascadia Code','Consolas',monospace;
  font-size:10px;font-weight:700;
}

/* ── Info panel ── */
#info-panel{
  position:fixed;bottom:20px;left:20px;
  background:#fff;border:1px solid var(--border);border-radius:10px;
  padding:14px 18px;z-index:250;max-width:400px;
  display:none;
  box-shadow:0 4px 20px rgba(0,0,0,.12);
}
#info-panel.open{display:block;}
#info-panel-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
#info-title{font-size:12px;font-weight:700;color:var(--accent);}
#info-close{
  background:none;border:1px solid var(--border);color:var(--muted);
  font-size:12px;cursor:pointer;padding:1px 6px;border-radius:4px;
}
#info-close:hover{color:var(--text);}
.info-meta-row{display:flex;gap:6px;font-size:10.5px;margin-bottom:3px;color:var(--muted);}
.info-meta-label{min-width:90px;flex-shrink:0;}
.info-meta-val{color:var(--text);font-family:'Cascadia Code','Consolas',monospace;}
#info-desc{font-size:11px;color:var(--muted);line-height:1.6;white-space:pre-wrap;margin:8px 0 10px;
  border-top:1px solid var(--border);padding-top:8px;}
.param-row{
  display:flex;gap:8px;font-family:'Cascadia Code','Consolas',monospace;font-size:10px;
  padding:3px 0;border-bottom:1px solid var(--border);
}
.param-nm{color:#6e40c9;min-width:120px;}
.param-def{color:var(--muted);}

/* ── Link tooltip ── */
.link-tooltip{
  position:fixed;z-index:400;background:#1f2328;color:#fff;
  font-size:10.5px;font-family:'Cascadia Code','Consolas',monospace;
  padding:4px 10px;border-radius:5px;pointer-events:none;display:none;white-space:nowrap;
}

/* ── Legend ── */
#legend{
  position:fixed;bottom:20px;right:var(--panw);
  background:#ffffffcc;border:1px solid var(--border);border-radius:8px;
  padding:8px 14px;z-index:150;display:flex;gap:14px;align-items:center;
  backdrop-filter:blur(6px);font-size:10px;transition:right .2s;
}
#legend.panel-closed{right:20px;}
.leg-item{display:flex;align-items:center;gap:5px;color:var(--muted);}
.leg-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0;}

#infobar{
  position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
  background:#ffffffcc;border:1px solid var(--border);border-radius:20px;
  padding:5px 14px;font-size:10px;color:var(--muted);z-index:100;
  pointer-events:none;backdrop-filter:blur(4px);
}
"""

    js = r"""
const DATA = __DATA__;

const STAGE_W = 172;
const SCALE   = 1.15;   // canvas schaal t.o.v. originele coördinaten

let transform = {x:60, y:40, z:1};
let isDragging = false, dragStart = {x:0,y:0}, transformStart = {x:0,y:0};
let selectedId = null;
let searchQuery = '';

const canvas    = document.getElementById('canvas');
const svgEl     = document.getElementById('svgl');
const detPanel  = document.getElementById('detail-panel');
const legend    = document.getElementById('legend');
const tooltip   = document.getElementById('link-tooltip');

// ── Stage posities berekenen
function stageX(s){ return s.x * SCALE; }
function stageY(s){ return s.y * SCALE; }
function stageCX(s){ return stageX(s) + STAGE_W/2; }
// hoogte hangt af van inhoud, we pakken een vaste waarde
function stageH(){ return 62; }
function stageCY(s){ return stageY(s) + stageH()/2; }

// ── Render stages
function renderStages(){
  DATA.stages.forEach(s => {
    const div = document.createElement('div');
    div.className = 'stage';
    div.id = 'stage-' + s.id;
    div.style.left   = stageX(s) + 'px';
    div.style.top    = stageY(s) + 'px';
    div.style.width  = STAGE_W + 'px';
    const mode = s.mode || 'OTHER';
    div.innerHTML = `
      <div class="stage-badge badge-${mode}">${mode}</div>
      <div class="stage-name">${esc(s.name)}</div>
    `;
    div.addEventListener('click', e => { e.stopPropagation(); selectStage(s.id); });
    canvas.appendChild(div);
  });
}

// ── Annotaties renderen (versleepbaar)
function renderAnnotations(){
  DATA.annotations.forEach((a, i) => {
    const div = document.createElement('div');
    div.className = 'annot';
    div.id = 'annot-' + i;
    div.style.left  = (a.x * SCALE) + 'px';
    div.style.top   = (a.y * SCALE) + 'px';
    div.style.width = Math.max(a.w * SCALE, 160) + 'px';

    // Grip-icoontje (zes puntjes, 2×3 grid)
    const grip = document.createElement('div');
    grip.className = 'annot-grip';
    grip.textContent = '⠿';
    div.appendChild(grip);

    const txt = document.createElement('span');
    txt.textContent = a.text;
    div.appendChild(txt);

    // Drag-logica: coördinaten in canvas-ruimte bijhouden
    let dragging = false, startMx, startMy, startLeft, startTop;

    div.addEventListener('mousedown', e => {
      e.stopPropagation();   // voorkom canvas-pan
      dragging  = true;
      startMx   = e.clientX;
      startMy   = e.clientY;
      startLeft = parseFloat(div.style.left);
      startTop  = parseFloat(div.style.top);
      div.style.zIndex = '90';
      div.style.boxShadow = '0 4px 16px rgba(0,0,0,.15)';
    });

    window.addEventListener('mousemove', e => {
      if(!dragging) return;
      // Verplaatsing in schermcoördinaten omzetten naar canvas-coördinaten
      const dx = (e.clientX - startMx) / transform.z;
      const dy = (e.clientY - startMy) / transform.z;
      div.style.left = (startLeft + dx) + 'px';
      div.style.top  = (startTop  + dy) + 'px';
    });

    window.addEventListener('mouseup', () => {
      if(!dragging) return;
      dragging = false;
      div.style.zIndex = '';
      div.style.boxShadow = '';
    });

    canvas.appendChild(div);
  });
}

// ── SVG links renderen
function renderLinks(){
  const stageMap = {};
  DATA.stages.forEach(s => stageMap[s.id] = s);

  // canvas bounding box
  const allX = DATA.stages.map(s => stageX(s) + STAGE_W + 100);
  const allY = DATA.stages.map(s => stageY(s) + stageH() + 80);
  const W = Math.max(...allX, 400);
  const H = Math.max(...allY, 300);
  svgEl.setAttribute('width', W);
  svgEl.setAttribute('height', H);

  // defs: drie arrow markers
  const defs = document.createElementNS('http://www.w3.org/2000/svg','defs');
  defs.innerHTML = `
    <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#0969da" opacity=".6"/>
    </marker>
    <marker id="arr-up" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#58a6ff"/>
    </marker>
    <marker id="arr-down" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#f0883e"/>
    </marker>`;
  svgEl.appendChild(defs);

  DATA.links.forEach((l, i) => {
    const src = stageMap[l.src];
    const tgt = stageMap[l.tgt];
    if (!src || !tgt) return;

    const x1 = stageCX(src) + STAGE_W/2 - 4;
    const y1 = stageCY(src);
    const x2 = stageX(tgt) - 4;
    const y2 = stageCY(tgt);
    const cx = (x1 + x2) / 2;
    const d  = `M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`;

    // Zichtbare lijn
    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('id', 'link-' + i);
    path.setAttribute('d', d);
    path.setAttribute('fill','none');
    path.setAttribute('stroke','#0969da');
    path.setAttribute('stroke-width','1.5');
    path.setAttribute('opacity','.5');
    path.setAttribute('marker-end','url(#arr)');
    svgEl.appendChild(path);

    // Onzichtbare hit-area voor tooltip
    const hit = document.createElementNS('http://www.w3.org/2000/svg','path');
    hit.setAttribute('d', d);
    hit.setAttribute('fill','none');
    hit.setAttribute('stroke','transparent');
    hit.setAttribute('stroke-width','12');
    hit.setAttribute('style','cursor:default');
    hit.addEventListener('mouseenter', e => { tooltip.textContent = l.name; tooltip.style.display = 'block'; moveLinkTooltip(e); });
    hit.addEventListener('mousemove',  e => moveLinkTooltip(e));
    hit.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
    svgEl.appendChild(hit);

    // Link label (kort, max 22 tekens)
    const mx = (x1+x2)/2, my = (y1+y2)/2 - 6;
    const bg = document.createElementNS('http://www.w3.org/2000/svg','rect');
    bg.setAttribute('x', mx - 36); bg.setAttribute('y', my - 8);
    bg.setAttribute('width', 72);  bg.setAttribute('height', 14);
    bg.setAttribute('rx', 4);      bg.setAttribute('fill','#f4f6f8');
    bg.setAttribute('opacity','.85');
    svgEl.appendChild(bg);
    const txt = document.createElementNS('http://www.w3.org/2000/svg','text');
    txt.setAttribute('id', 'linktxt-' + i);
    txt.setAttribute('x', mx); txt.setAttribute('y', my + 2);
    txt.setAttribute('text-anchor','middle');
    txt.setAttribute('font-size','8');
    txt.setAttribute('font-family','IBM Plex Mono,monospace');
    txt.setAttribute('fill','#656d76');
    txt.setAttribute('pointer-events','none');
    txt.textContent = l.name.length > 22 ? l.name.slice(0,20)+'…' : l.name;
    svgEl.appendChild(txt);
  });
}

function moveLinkTooltip(e){
  tooltip.style.left = (e.clientX + 12) + 'px';
  tooltip.style.top  = (e.clientY - 28) + 'px';
}

// ── Upstream / downstream highlight
function getConnected(stageId){
  const upstream = new Set(), downstream = new Set();
  DATA.links.forEach(l => {
    if(l.tgt === stageId) upstream.add(l.src);
    if(l.src === stageId) downstream.add(l.tgt);
  });
  return {upstream, downstream};
}

function applyConnectionHighlight(stageId){
  const {upstream, downstream} = getConnected(stageId);
  DATA.links.forEach((l, i) => {
    const path = document.getElementById('link-' + i);
    const txt  = document.getElementById('linktxt-' + i);
    if(!path) return;
    if(l.tgt === stageId){
      path.setAttribute('stroke','#58a6ff'); path.setAttribute('stroke-width','2.5');
      path.setAttribute('opacity','1'); path.setAttribute('marker-end','url(#arr-up)');
      if(txt) txt.setAttribute('fill','#58a6ff');
    } else if(l.src === stageId){
      path.setAttribute('stroke','#f0883e'); path.setAttribute('stroke-width','2.5');
      path.setAttribute('opacity','1'); path.setAttribute('marker-end','url(#arr-down)');
      if(txt) txt.setAttribute('fill','#f0883e');
    } else {
      path.setAttribute('stroke','#0969da'); path.setAttribute('stroke-width','1.5');
      path.setAttribute('opacity','.15'); path.setAttribute('marker-end','url(#arr)');
      if(txt) txt.setAttribute('fill','#c0c8d0');
    }
  });
  DATA.stages.forEach(s => {
    const el = document.getElementById('stage-' + s.id);
    if(!el) return;
    el.classList.remove('hl-up','hl-down');
    if(upstream.has(s.id))   el.classList.add('hl-up');
    if(downstream.has(s.id)) el.classList.add('hl-down');
  });
}

function clearConnectionHighlight(){
  DATA.links.forEach((l, i) => {
    const path = document.getElementById('link-' + i);
    const txt  = document.getElementById('linktxt-' + i);
    if(!path) return;
    path.setAttribute('stroke','#0969da'); path.setAttribute('stroke-width','1.5');
    path.setAttribute('opacity','.5'); path.setAttribute('marker-end','url(#arr)');
    if(txt) txt.setAttribute('fill','#656d76');
  });
  DATA.stages.forEach(s => {
    const el = document.getElementById('stage-' + s.id);
    if(el) el.classList.remove('hl-up','hl-down');
  });
}

// ── Zoekfunctie
function applySearch(q){
  searchQuery = q.trim().toLowerCase();
  const countEl = document.getElementById('search-count');
  const clearEl = document.getElementById('search-clear');
  if(!searchQuery){
    DATA.stages.forEach(s => {
      const el = document.getElementById('stage-' + s.id);
      if(el) el.classList.remove('dimmed','search-match');
    });
    countEl.textContent = ''; clearEl.style.display = 'none'; return;
  }
  clearEl.style.display = 'block';
  let matches = 0;
  DATA.stages.forEach(s => {
    const el = document.getElementById('stage-' + s.id);
    if(!el) return;
    const hit = s.name.toLowerCase().includes(searchQuery)
             || (s.type_label && s.type_label.toLowerCase().includes(searchQuery))
             || (s.table && s.table.toLowerCase().includes(searchQuery));
    el.classList.remove('dimmed','search-match');
    if(hit){ el.classList.add('search-match'); matches++; }
    else    { el.classList.add('dimmed'); }
  });
  countEl.textContent = matches + ' match' + (matches !== 1 ? 'es' : '');
}

function clearSearch(){
  document.getElementById('search-input').value = '';
  applySearch('');
}

// ── SQL syntax highlighting
function highlightSQL(sql){
  const keywords = /\b(SELECT|FROM|WHERE|AND|OR|NOT|IN|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|GROUP BY|ORDER BY|HAVING|DISTINCT|AS|WITH|UNION|INSERT|INTO|UPDATE|SET|DELETE|CASE|WHEN|THEN|ELSE|END|NULL|IS|NVL|NVL2|DECODE|TRIM|UPPER|LOWER|TO_DATE|TO_CHAR|TRUNC|SYSDATE|TIMESTAMP|BY|INTO|VALUES)\b/gi;
  const escaped = sql
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/--[^\n]*/g, m => `<span class="cm">${m}</span>`)
    .replace(/'[^']*'/g, m => `<span class="st">${m}</span>`);
  return escaped.replace(keywords, m => `<span class="kw">${m.toUpperCase()}</span>`);
}

// ── Stage selecteren & detail tonen
function selectStage(id){
  if(selectedId){
    const prev = document.getElementById('stage-'+selectedId);
    if(prev) prev.classList.remove('selected');
  }
  selectedId = id;
  const el = document.getElementById('stage-'+id);
  if(el) el.classList.add('selected');
  const s = DATA.stages.find(x => x.id === id);
  if(s){
    showDetail(s);
    applyConnectionHighlight(id);
    // Info panel sluiten als het open is
    document.getElementById('info-panel').classList.remove('open');
  }
}

// Pass-through = derivation is gewoon "link.KOLOMNAAM" zonder extra logica
function isPassThrough(deriv){
  if(!deriv) return true;
  const d = deriv.trim();
  // patroon: optioneel "lnk_iets." gevolgd door één identifier, niets meer
  return /^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$/.test(d)
      || /^[A-Za-z_][A-Za-z0-9_]*$/.test(d);
}

const JOIN_OP_LABEL = {
  'join':           'Inner Join',
  'leftouterjoin':  'Left Outer Join',
  'rightouterjoin': 'Right Outer Join',
  'fullouterjoin':  'Full Outer Join',
};
const AGG_FUNC_LABEL = {
  'max':'MAX','min':'MIN','sum':'SUM','count':'COUNT',
  'first':'FIRST','last':'LAST','range':'RANGE',
  'std_dev':'STD_DEV','variance':'VARIANCE',
};
const MODE_ICON = {
  SOURCE:'⬇', TARGET:'⬆', TRANSFORM:'⚙', JOIN:'⊕', AGGREGATE:'∑'
};
const MODE_COLOR = {
  SOURCE:'#1a7f37', TARGET:'#cf222e', TRANSFORM:'#6e40c9',
  JOIN:'#953800', AGGREGATE:'#0550ae'
};

function showDetail(s){
  const mode  = s.mode || 'OTHER';
  const color = MODE_COLOR[mode] || '#848d97';
  const icon  = MODE_ICON[mode]  || '◻';

  document.getElementById('dp-icon').style.background = color + '22';
  document.getElementById('dp-icon').style.color      = color;
  document.getElementById('dp-icon').textContent      = icon;
  document.getElementById('dp-title').textContent     = s.name;
  document.getElementById('dp-sub').textContent       = (s.type_label || s.type) + ' · ' + mode;

  let html = '';

  // Tabel / writemode (target)
  if(s.table){
    html += `<div class="dp-section">
      <div class="dp-section-title">Doel</div>
      <div class="dp-row">
        <span class="dp-key">Tabel</span>
        <span class="dp-val accent">${esc(s.table)}</span>
      </div>
      ${s.wm ? `<div class="dp-row"><span class="dp-key">Write Mode</span><span class="dp-val">${esc(s.wm)}</span></div>` : ''}
    </div>`;
  }

  // SQL
  if(s.sql){
    html += `<div class="dp-section">
      <div class="dp-section-title">SQL</div>
      <div class="sql-block">${highlightSQL(s.sql)}</div>
    </div>`;
  }

  // Where clause (SOURCE)
  if(s.where_clause){
    html += `<div class="dp-section">
      <div class="dp-section-title">Where clause</div>
      <div class="sql-block">${highlightSQL(s.where_clause)}</div>
    </div>`;
  }

  // Before / After SQL (TARGET)
  if(s.before_sql || s.after_sql){
    html += `<div class="dp-section">
      <div class="dp-section-title">Before / After SQL</div>`;
    if(s.before_sql) html += `<div style="font-size:9px;color:var(--muted);margin-bottom:3px;text-transform:uppercase;letter-spacing:.4px">Before</div>
      <div class="sql-block" style="margin-bottom:8px">${highlightSQL(s.before_sql)}</div>`;
    if(s.after_sql)  html += `<div style="font-size:9px;color:var(--muted);margin-bottom:3px;text-transform:uppercase;letter-spacing:.4px">After</div>
      <div class="sql-block">${highlightSQL(s.after_sql)}</div>`;
    html += `</div>`;
  }

  // Oracle SOURCE connector instellingen
  if(s.mode === 'SOURCE' && (s.array_size || s.record_count || s.prefetch_row_count || s.partitioned_reads)){
    html += `<div class="dp-section">
      <div class="dp-section-title">Connector instellingen</div>`;
    if(s.array_size)   html += `<div class="dp-row"><span class="dp-key">Array size</span><span class="dp-val">${esc(s.array_size)}</span></div>`;
    if(s.record_count) html += `<div class="dp-row"><span class="dp-key">Record count</span><span class="dp-val">${esc(s.record_count)}</span></div>`;
    if(s.prefetch_row_count && s.prefetch_row_count !== '0' && s.prefetch_row_count !== '1')
      html += `<div class="dp-row"><span class="dp-key">Prefetch rows</span><span class="dp-val">${esc(s.prefetch_row_count)}</span></div>`;
    if(s.prefetch_memory_size && s.prefetch_memory_size !== '0')
      html += `<div class="dp-row"><span class="dp-key">Prefetch mem (KB)</span><span class="dp-val">${esc(s.prefetch_memory_size)}</span></div>`;
    html += `<div class="dp-row"><span class="dp-key">Partitioned reads</span><span class="dp-val">
      ${s.partitioned_reads ? '<span class="dp-badge ok">✓ Aan</span>' : '<span class="dp-badge no">Uit</span>'}
    </span></div>`;
    html += `</div>`;
  }

  // Oracle TARGET connector instellingen
  if(s.mode === 'TARGET' && (s.array_size || s.record_count || s.drop_unmatched !== undefined)){
    html += `<div class="dp-section">
      <div class="dp-section-title">Connector instellingen</div>`;
    if(s.array_size)   html += `<div class="dp-row"><span class="dp-key">Array size</span><span class="dp-val">${esc(s.array_size)}</span></div>`;
    if(s.record_count) html += `<div class="dp-row"><span class="dp-key">Record count</span><span class="dp-val">${esc(s.record_count)}</span></div>`;
    html += `<div class="dp-row"><span class="dp-key">Drop unmatched</span><span class="dp-val">
      ${s.drop_unmatched ? '<span class="dp-badge warn">✓ Aan</span>' : '<span class="dp-badge no">Uit</span>'}
    </span></div>`;
    html += `<div class="dp-row"><span class="dp-key">Fail on row error</span><span class="dp-val">
      ${s.fail_on_row_error ? '<span class="dp-badge ok">✓ Aan</span>' : '<span class="dp-badge warn">Uit</span>'}
    </span></div>`;
    html += `</div>`;
  }

  // Bulk Load extra
  if(s.wm === 'BULK LOAD'){
    html += `<div class="dp-section">
      <div class="dp-section-title">Bulk Load opties</div>`;
    if(s.direct_parallelism) html += `<div class="dp-row"><span class="dp-key">Direct parallelism</span><span class="dp-val">${esc(s.direct_parallelism)}</span></div>`;
    if(s.buffer_size)        html += `<div class="dp-row"><span class="dp-key">Buffer size</span><span class="dp-val">${esc(s.buffer_size)}</span></div>`;
    if(s.skip_indexes)       html += `<div class="dp-row"><span class="dp-key">Skip indexes</span><span class="dp-val">${esc(s.skip_indexes)}</span></div>`;
    if(s.date_cache_size)    html += `<div class="dp-row"><span class="dp-key">Date cache size</span><span class="dp-val">${esc(s.date_cache_size)}</span></div>`;
    html += `<div class="dp-row"><span class="dp-key">No log</span><span class="dp-val">
      ${s.no_log ? '<span class="dp-badge warn">✓ Aan</span>' : '<span class="dp-badge no">Uit</span>'}
    </span></div>`;
    html += `<div class="dp-row"><span class="dp-key">Rebuild indexes</span><span class="dp-val">
      ${s.rebuild_indexes ? '<span class="dp-badge ok">✓ Aan</span>' : '<span class="dp-badge no">Uit</span>'}
    </span></div>`;
    html += `</div>`;
  }

  // Links in/uit
  const inLinks  = DATA.links.filter(l => l.tgt === s.id);
  const outLinks = DATA.links.filter(l => l.src === s.id);
  if(inLinks.length || outLinks.length){
    html += `<div class="dp-section"><div class="dp-section-title">Verbindingen</div>`;
    inLinks.forEach(l => {
      const src = DATA.stages.find(x => x.id === l.src);
      html += `<div class="dp-row">
        <span class="dp-key" style="color:#848d97">← in</span>
        <span class="dp-val">${esc(src?.name || l.src)} <span style="color:#484f58">/ ${esc(l.name)}</span></span>
      </div>`;
    });
    outLinks.forEach(l => {
      const tgt = DATA.stages.find(x => x.id === l.tgt);
      html += `<div class="dp-row">
        <span class="dp-key" style="color:#58a6ff">→ uit</span>
        <span class="dp-val">${esc(tgt?.name || l.tgt)} <span style="color:#484f58">/ ${esc(l.name)}</span></span>
      </div>`;
    });
    html += '</div>';
  }

  // Transformer: constraint (filter) + kolommen
  if(s.mode === 'TRANSFORM'){
    // Filter/constraint
    if(s.constraint){
      html += `<div class="dp-section">
        <div class="dp-section-title">⚠ Filter (constraint)</div>
        <div class="sql-block">${esc(s.constraint)}</div>
      </div>`;
    }

    // Stage variabelen (intermediaire berekeningen)
    if(s.stage_vars && s.stage_vars.length){
      html += `<div class="dp-section">
        <div class="dp-section-title">Stage variabelen (${s.stage_vars.length})</div>
        <table class="col-table">
          <thead><tr><th>Variabele</th><th>Berekening</th></tr></thead>
          <tbody>
            ${s.stage_vars.map(v => `<tr>
              <td class="col-name">${esc(v.name)}</td>
              <td class="col-deriv">${esc(v.derivation)}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    }

    // Output kolommen: splits in pass-through vs. berekend
    if(s.columns && s.columns.length){
      const passThrough = s.columns.filter(c => isPassThrough(c.deriv));
      const computed    = s.columns.filter(c => !isPassThrough(c.deriv));

      if(computed.length){
        html += `<div class="dp-section">
          <div class="dp-section-title">🔧 Berekende kolommen (${computed.length})</div>
          <table class="col-table">
            <thead><tr><th>Kolom</th><th>Logica</th></tr></thead>
            <tbody>
              ${computed.map(c => `<tr>
                <td class="col-name">${esc(c.name)}</td>
                <td class="col-deriv col-logic">${esc(c.deriv)}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
      }
      if(passThrough.length){
        html += `<div class="dp-section">
          <div class="dp-section-title">→ Pass-through kolommen (${passThrough.length})</div>
          <div class="passthrough-grid">
            ${passThrough.map(c => `<div class="pt-item">
              <span class="pt-name">${esc(c.name)}</span>
              <span class="pt-src">${esc(c.deriv)}</span>
            </div>`).join('')}
          </div>
        </div>`;
      }
    }

  } else if(s.mode === 'JOIN' && s.join_props){
    const jp = s.join_props;
    const opLabel = JOIN_OP_LABEL[jp.operator] || jp.operator;
    html += `<div class="dp-section">
      <div class="dp-section-title">Join type</div>
      <div class="join-type-badge">${esc(opLabel)}</div>
    </div>`;
    if(jp.keys && jp.keys.length){
      html += `<div class="dp-section">
        <div class="dp-section-title">⚿ Join sleutels (${jp.keys.length})</div>
        <div class="key-grid">
          ${jp.keys.map(k => `<div class="key-chip">${esc(k)}</div>`).join('')}
        </div>
      </div>`;
    }
    // Input links tonen
    const inLinks = DATA.links.filter(l => l.tgt === s.id);
    if(inLinks.length){
      html += `<div class="dp-section">
        <div class="dp-section-title">Gekoppelde stromen</div>
        ${inLinks.map((l,i) => {
          const src = DATA.stages.find(x => x.id === l.src);
          const isDriver = i === 0;
          return `<div class="dp-row">
            <span class="dp-key" style="color:${isDriver?'#0969da':'#656d76'}">${isDriver?'driving':'reference'}</span>
            <span class="dp-val">${esc(src?.name || l.src)} <span style="color:#848d97">/ ${esc(l.name)}</span></span>
          </div>`;
        }).join('')}
      </div>`;
    }

  } else if(s.mode === 'AGGREGATE' && s.agg_props){
    const ap = s.agg_props;
    if(ap.keys && ap.keys.length){
      html += `<div class="dp-section">
        <div class="dp-section-title">GROUP BY sleutels (${ap.keys.length})</div>
        <div class="key-grid">
          ${ap.keys.map(k => `<div class="key-chip key-chip-grp">${esc(k)}</div>`).join('')}
        </div>
      </div>`;
    }
    if(ap.aggregations && ap.aggregations.length){
      html += `<div class="dp-section">
        <div class="dp-section-title">Aggregaties (${ap.aggregations.length})</div>
        <table class="col-table">
          <thead><tr><th>Kolom</th><th>Functie</th></tr></thead>
          <tbody>
            ${ap.aggregations.map(a => {
              const fn = AGG_FUNC_LABEL[a.func] || a.func || '—';
              const fnColor = a.func === 'max'?'#1a7f37': a.func === 'min'?'#cf222e': a.func === 'sum'?'#0550ae':'#953800';
              return `<tr>
                <td class="col-name">${esc(a.col)}</td>
                <td><span class="fn-badge" style="color:${fnColor}">${esc(fn)}</span></td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;
    }
    html += `<div class="dp-section">
      <div class="dp-section-title">Methode</div>
      <div class="dp-row"><span class="dp-key">Sorteer</span><span class="dp-val">${esc(ap.method)}</span></div>
    </div>`;

  } else {
    // Niet-transformer/join/agg: gewone kolom tabel
    if(s.columns && s.columns.length){
      html += `<div class="dp-section">
        <div class="dp-section-title">Output kolommen (${s.columns.length})</div>
        <table class="col-table">
          <thead><tr><th>Naam</th><th>Type</th><th>Afleiding</th></tr></thead>
          <tbody>
            ${s.columns.map(c => `<tr>
              <td>${esc(c.name)}</td>
              <td class="col-type">${esc(c.type)}</td>
              <td class="col-deriv">${esc(c.deriv)}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    }
  }

  document.getElementById('dp-body').innerHTML = html;
  detPanel.classList.add('open');
  legend.classList.remove('panel-closed');
}

function closeDetail(){
  detPanel.classList.remove('open');
  legend.classList.add('panel-closed');
  clearConnectionHighlight();
  if(selectedId){
    const el = document.getElementById('stage-'+selectedId);
    if(el) el.classList.remove('selected');
    selectedId = null;
  }
}

// ── Info panel (job meta)
function toggleInfo(){
  document.getElementById('info-panel').classList.toggle('open');
}

function buildInfoPanel(){
  document.getElementById('info-title').textContent = DATA.job;
  document.getElementById('info-desc').textContent  = DATA.description || '—';
  const pc = document.getElementById('params-container');
  if(DATA.params.length){
    DATA.params.forEach(p => {
      const row = document.createElement('div');
      row.className = 'param-row';
      row.innerHTML = `<span class="param-nm">${esc(p.name)}</span><span class="param-def">${esc(p.default || '—')}</span>`;
      pc.appendChild(row);
    });
  } else {
    pc.innerHTML = '<div style="font-size:10.5px;color:var(--muted)">Geen parameters</div>';
  }
}

// ── Pan / zoom
const wrap = document.getElementById('canvas-wrap');
wrap.addEventListener('wheel', e => {
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  const rect  = wrap.getBoundingClientRect();
  const mx    = e.clientX - rect.left;
  const my    = e.clientY - rect.top;
  transform.x = mx - (mx - transform.x) * delta;
  transform.y = my - (my - transform.y) * delta;
  transform.z = Math.max(0.15, Math.min(3, transform.z * delta));
  applyTransform();
}, {passive: false});

wrap.addEventListener('mousedown', e => {
  if(e.target.closest('.stage')) return;
  isDragging   = true;
  dragStart    = {x: e.clientX, y: e.clientY};
  transformStart = {x: transform.x, y: transform.y};
  wrap.style.cursor = 'grabbing';
});
window.addEventListener('mousemove', e => {
  if(!isDragging) return;
  transform.x = transformStart.x + e.clientX - dragStart.x;
  transform.y = transformStart.y + e.clientY - dragStart.y;
  applyTransform();
});
window.addEventListener('mouseup', () => {
  isDragging = false;
  wrap.style.cursor = '';
});
wrap.addEventListener('click', e => {
  if(!e.target.closest('.stage')) closeDetail();
});

function applyTransform(){
  canvas.style.transform = `translate(${transform.x}px,${transform.y}px) scale(${transform.z})`;
}

function fit(){
  if(!DATA.stages.length) return;
  const rect  = wrap.getBoundingClientRect();
  const minX  = Math.min(...DATA.stages.map(s => stageX(s)));
  const maxX  = Math.max(...DATA.stages.map(s => stageX(s) + STAGE_W));
  const minY  = Math.min(...DATA.stages.map(s => stageY(s)));
  const maxY  = Math.max(...DATA.stages.map(s => stageY(s) + stageH()));
  const cw    = maxX - minX + 80;
  const ch    = maxY - minY + 80;
  const z     = Math.min((rect.width - 80) / cw, (rect.height - 80) / ch, 1.5);
  transform.z = z;
  transform.x = (rect.width  - cw*z)/2 - minX*z + 40*z;
  transform.y = (rect.height - ch*z)/2 - minY*z + 40*z;
  applyTransform();
}

function resetZoom(){
  transform.z = 1;
  transform.x = 60;
  transform.y = 40;
  applyTransform();
}

function esc(s){
  if(!s) return '';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init
renderAnnotations();
renderLinks();
renderStages();
buildInfoPanel();
fit();

// Zoek event listeners
document.getElementById('search-input').addEventListener('input', e => applySearch(e.target.value));
document.getElementById('search-input').addEventListener('keydown', e => {
  if(e.key === 'Escape'){ clearSearch(); e.target.blur(); }
});
document.getElementById('search-clear').addEventListener('click', clearSearch);
window.addEventListener('keydown', e => {
  if((e.ctrlKey || e.metaKey) && e.key === 'f'){
    e.preventDefault();
    document.getElementById('search-input').focus();
    document.getElementById('search-input').select();
  }
});
"""

    js = js.replace('__DATA__', job_data_json)

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_esc} — DataStage Job Flow</title>
<meta name="generator" content="ds_job_flow.py">
<meta name="source-file" content="{source_esc}">
<meta name="export-date" content="{htmllib.escape(export_date)}">
<style>{css}</style>
</head>
<body>
<div id="toolbar">
  <div id="logo">DS</div>
  <div id="title-block">
    <div id="job-name">{title_esc}</div>
    <div id="job-meta">DataStage Parallel Job · {stage_count} stages · {src_count} source · {tgt_count} target · {link_count} links · Export {htmllib.escape(export_date)}</div>
  </div>
  <div id="toolbar-right">
    <div id="search-wrap">
      <input id="search-input" type="text" placeholder="Zoek stage… (Ctrl+F)" autocomplete="off">
      <button id="search-clear" title="Wis zoekopdracht">✕</button>
      <span id="search-count"></span>
    </div>
    <button class="tbtn" onclick="fit()">⊡ Fit</button>
    <button class="tbtn" onclick="resetZoom()">1:1</button>
    <button id="info-btn" onclick="toggleInfo()">ℹ Info / params</button>
  </div>
</div>

<div id="canvas-wrap">
  <div id="canvas">
    <svg id="svgl" style="position:absolute;top:0;left:0;pointer-events:none;overflow:visible;"></svg>
  </div>
</div>

<div id="detail-panel">
  <div id="dp-head">
    <div id="dp-icon">◻</div>
    <div style="flex:1;min-width:0;">
      <div id="dp-title">—</div>
      <div id="dp-sub"></div>
    </div>
    <button id="dp-close" onclick="closeDetail()">✕</button>
  </div>
  <div id="dp-body"></div>
</div>

<div id="info-panel">
  <div id="info-panel-head">
    <div id="info-title"></div>
    <button id="info-close" onclick="toggleInfo()">✕</button>
  </div>
  <div class="info-meta-row">
    <span class="info-meta-label">Bronbestand</span>
    <span class="info-meta-val">{source_esc}</span>
  </div>
  <div class="info-meta-row">
    <span class="info-meta-label">Export datum</span>
    <span class="info-meta-val">{htmllib.escape(export_date)}</span>
  </div>
  <div class="info-meta-row">
    <span class="info-meta-label">Stages / links</span>
    <span class="info-meta-val">{stage_count} stages · {link_count} links</span>
  </div>
  <div id="info-desc"></div>
  <div id="params-container"></div>
</div>

<div id="legend" class="panel-closed">
  <div class="leg-item"><div class="leg-dot" style="background:#3fb950"></div>SOURCE</div>
  <div class="leg-item"><div class="leg-dot" style="background:#f85149"></div>TARGET</div>
  <div class="leg-item"><div class="leg-dot" style="background:#d2a8ff"></div>TRANSFORM</div>
  <div class="leg-item"><div class="leg-dot" style="background:#ffa657"></div>JOIN</div>
  <div class="leg-item"><div class="leg-dot" style="background:#79c0ff"></div>AGGREGATE</div>
  <div class="leg-item" style="border-left:1px solid var(--border);padding-left:10px;color:#58a6ff">▲ upstream</div>
  <div class="leg-item" style="color:#f0883e">▼ downstream</div>
</div>

<div id="infobar">Scroll = zoom · Sleep = pan · Klik stage voor details · Ctrl+F = zoeken</div>
<div id="link-tooltip" class="link-tooltip"></div>

<script>{js}</script>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
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
