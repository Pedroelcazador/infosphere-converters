#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""IBM DataStage DSExport XML → interactieve Sequencer Flowchart (HTML)

Genereert een standalone HTML met een interactieve flowchart per sequencer-job.
Per sequencer: alle activiteiten als nodes, OK/NOK/onvoorwaardelijk paden als
gekleurde verbindingen. Klik op een job-activiteit om SQL en tabel-details te zien.

Gebruik: leg één DSExport XML in de map en draai `python3 ds_flow.py`
Output : <bestandsnaam>_Flow.html  +  ds_flow.log
"""

import re, html as htmllib, sys, logging, json, importlib.util
from collections import deque
from pathlib import Path
from xml.etree import ElementTree as ET

_ds_path = Path(__file__).resolve().parent.parent / 'ds_convert' / 'ds_convert.py'
_ds_spec = importlib.util.spec_from_file_location('ds_convert', _ds_path)
ds = importlib.util.module_from_spec(_ds_spec)
sys.modules['ds_convert'] = ds
_ds_spec.loader.exec_module(ds)

_dsj_path = Path(__file__).resolve().parent.parent / 'ds_job_flow' / 'ds_job_flow.py'
_dsj_spec = importlib.util.spec_from_file_location('ds_job_flow', _dsj_path)
dsj = importlib.util.module_from_spec(_dsj_spec)
sys.modules['ds_job_flow'] = dsj
_dsj_spec.loader.exec_module(dsj)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'ds_flow.log'

log = logging.getLogger(__name__)

WM_LABEL = {'0': 'INSERT', '1': 'UPDATE', '6': 'BULK LOAD', '9': 'UPSERT/MERGE'}

SKIP_SEQ = frozenset({
    'JobDefn', 'ContainerView',
    'JSActivityInput', 'JSActivityOutput',
    'Annotation', 'TextAnnotation',
})

RTYPE_KIND = {
    'JSJobActivity':        'job',
    'CJobActivity':         'job',
    'JSSequencer':          'sync',
    'CSequencer':           'sync',
    'JSTerminatorActivity': 'stop',
    'CTerminatorActivity':  'stop',
    'JSCondition':          'condition',
    'CCondition':           'condition',
    'JSUserVarsActivity':   'vars',
    'CUserVarsActivity':    'vars',
    'JSRoutineActivity':    'routine',
    'CRoutineActivity':     'routine',
    'JSExecCmdActivity':    'exec',
    'CExecCommandActivity': 'exec',
    'JSStartLoopActivity':  'loop_start',
    'CStartLoopActivity':   'loop_start',
    'JSEndLoopActivity':    'loop_end',
    'CEndLoopActivity':     'loop_end',
    'JSExceptionHandler':   'exception',
    'CExceptionHandler':    'exception',
}


# ── Parallel job details ──────────────────────────────────────────────────────

def extract_par_details(job_elem):
    stages = []
    for rec in job_elem.findall('Record'):
        rtype      = rec.get('Type', '')
        rid        = rec.get('Identifier', '')
        stage_type = ds.prop(rec, 'StageType') or rtype
        if stage_type != 'OracleConnectorPX':
            continue
        name = ds.prop(rec, 'Name') or rid
        mode = 'TARGET' if ds.prop(rec, 'InputPins') else 'SOURCE'
        xp   = ds.get_xmlprops_tree(rec)
        info = {'name': name, 'mode': mode,
                'sql': '', 'table': '', 'writemode': '',
                'before_sql': '', 'after_sql': '',
                'gen_sql': '', 'array': '', 'where': ''}
        if xp is not None:
            if mode == 'SOURCE':
                info['sql']     = ds.xprop(xp, 'SelectStatement') or ds.xprop(xp, 'UserDefinedSQL')
                info['gen_sql'] = ds.xprop(xp, 'GenerateSQL')
                info['array']   = ds.xprop(xp, 'ArraySize')
                info['where']   = ds.xprop(xp, 'WhereClause')
            else:
                wm = ds.xprop(xp, 'WriteMode')
                info['table']      = ds.xprop(xp, 'TableName').lower()
                info['writemode']  = WM_LABEL.get(wm, wm)
                info['gen_sql']    = ds.xprop(xp, 'GenerateSQL')
                info['array']      = ds.xprop(xp, 'ArraySize')
                info['before_sql'] = ds.xprop(xp, 'BeforeSQL', 'BeforeSQLStatement')
                info['after_sql']  = ds.xprop(xp, 'AfterSQL',  'AfterSQLStatement')
        stages.append(info)
    return stages


# ── Job flow HTML genereren (voor iframe in modal) ────────────────────────────

def generate_job_flow_html(job_elem, jobname, export_date, xml_stem):
    """Genereer volledige ds_job_flow HTML voor één parallel job en sla op in output/.
    Geeft de bestandsnaam terug, of None bij mislukking."""
    try:
        xml_str  = ET.tostring(job_elem, encoding='unicode')
        job_data = dsj.parse_job(xml_str)
        job_html = dsj.build_html(job_data, export_date, xml_stem)
        safe     = re.sub(r'[^\w\-]', '_', jobname)
        fname    = f'{xml_stem}_{safe}_JobFlow.html'
        (OUTPUT_DIR / fname).write_text(job_html, encoding='utf-8')
        return fname
    except (SystemExit, Exception) as exc:
        log.warning('Job flow genereren mislukt voor %s: %s', jobname, exc)
        return None


# ── Sequencer parsen ──────────────────────────────────────────────────────────

def parse_sequencer(job_id, job_elem, par_elems, export_date, xml_stem):
    records = {
        rec.get('Identifier', ''): (rec.get('Type', ''), rec)
        for rec in job_elem.findall('Record')
    }

    # Beschrijving uit ROOT
    desc = ''
    root_rec = job_elem.find("Record[@Identifier='ROOT']")
    if root_rec is not None:
        raw = ds.prop(root_rec, 'Description') or ''
        func_desc, _ = ds.parse_description(raw)
        desc = func_desc or ''

    # pin → stage map
    pin_to_stage = {}
    for rid, (rtype, rec) in records.items():
        for pid in (ds.prop(rec, 'InputPins') + '|' + ds.prop(rec, 'OutputPins')).split('|'):
            pid = pid.strip()
            if pid:
                pin_to_stage[pid] = rid

    # Links via output-pin Partners (dedupliceer op from/to/cond)
    links   = []
    seen_lk = set()
    for rid, (rtype, rec) in records.items():
        if rtype not in ('JSActivityOutput', 'CActivityOutput', 'StdOutput'):
            continue
        partner = ds.prop(rec, 'Partner')
        if not partner:
            continue
        target  = partner.split('|')[0]
        source  = pin_to_stage.get(rid)
        if not source or source == target:
            continue
        cond = ds.prop(rec, 'ConditionType')
        name = ds.prop(rec, 'Name') or ''
        key  = (source, target, cond)
        if key in seen_lk:
            continue
        seen_lk.add(key)
        links.append({'from': source, 'to': target, 'cond': cond, 'name': name})

    # Nodes
    nodes = {}
    for rid, (rtype, rec) in records.items():
        if rtype in SKIP_SEQ:
            continue
        name    = ds.prop(rec, 'Name') or rid
        kind    = RTYPE_KIND.get(rtype, 'other')
        jobname = ds.prop(rec, 'Jobname') or ''
        gate    = ''
        if kind == 'sync':
            st   = ds.prop(rec, 'SequencerType')
            gate = 'AND' if st == '1' else 'OR' if st == '0' else '?'

        par_stages     = []
        job_flow_file  = None
        if kind == 'job' and jobname and jobname in par_elems:
            par_stages    = extract_par_details(par_elems[jobname])
            job_flow_file = generate_job_flow_html(par_elems[jobname], jobname, export_date, xml_stem)

        nodes[rid] = {
            'id': rid, 'name': name, 'kind': kind,
            'rtype': rtype, 'jobname': jobname,
            'gate': gate, 'par_stages': par_stages,
            'job_flow_file': job_flow_file,
        }

    # Topologische rank via Kahn (cycles landen aan het eind)
    in_deg = {nid: 0 for nid in nodes}
    for l in links:
        if l['to'] in in_deg:
            in_deg[l['to']] += 1

    queue = deque(nid for nid, d in in_deg.items() if d == 0)
    topo  = {}
    rank  = 0
    while queue:
        nxt = deque()
        while queue:
            nid = queue.popleft()
            topo[nid] = rank
            for l in links:
                if l['from'] == nid and l['to'] in in_deg:
                    in_deg[l['to']] -= 1
                    if in_deg[l['to']] == 0:
                        nxt.append(l['to'])
        queue = nxt
        rank += 1

    for nid in nodes:
        if nid not in topo:
            topo[nid] = rank

    return {
        'id':          job_id,
        'description': desc,
        'nodes':       list(nodes.values()),
        'links':       links,
        'topo_rank':   topo,
    }


# ── Alle jobs parsen ──────────────────────────────────────────────────────────

def parse_all(content, export_date='?', xml_stem='export'):
    root = ET.fromstring(content)
    job_elems = root.findall('Job')

    par_elems = {}
    for job_elem in job_elems:
        jid = job_elem.get('Identifier', '')
        if not jid.startswith('seq_'):
            par_elems[jid] = job_elem

    sequencers = []
    for job_elem in job_elems:
        jid = job_elem.get('Identifier', '')
        if not jid.startswith('seq_'):
            continue
        rtypes = [rec.get('Type', '') for rec in job_elem.findall('Record')]
        if not any(r in ('JSJobActivity','CJobActivity','JSSequencer','CSequencer')
                   for r in rtypes):
            continue
        log.info('  Sequencer: %s', jid)
        sequencers.append(parse_sequencer(jid, job_elem, par_elems, export_date, xml_stem))

    # Fallback: geen sequencers → toon parallel jobs als simpele nodes
    if not sequencers:
        log.info('  Geen sequencers gevonden — parallel jobs als overzicht weergeven')
        nodes = []
        for jid, job_elem in par_elems.items():
            par_stages    = extract_par_details(job_elem)
            job_flow_file = generate_job_flow_html(job_elem, jid, export_date, xml_stem)
            root_rec      = job_elem.find("Record[@Identifier='ROOT']")
            desc = ''
            if root_rec is not None:
                raw = ds.prop(root_rec, 'Description') or ''
                func_desc, _ = ds.parse_description(raw)
                desc = func_desc or ''
            nodes.append({
                'id': jid, 'name': jid, 'kind': 'job',
                'rtype': 'JSJobActivity', 'jobname': jid,
                'gate': '', 'par_stages': par_stages,
                'job_flow_file': job_flow_file,
                'description': desc,
            })
        # Geen links bij enkelvoudige jobs
        topo = {n['id']: i for i, n in enumerate(nodes)}
        sequencers.append({
            'id':          'Jobs overzicht',
            'description': f'{len(nodes)} parallel job(s) in deze export',
            'nodes':       nodes,
            'links':       [],
            'topo_rank':   topo,
        })

    return sequencers


# ── HTML genereren ────────────────────────────────────────────────────────────

_TEMPLATE = (SCRIPT_DIR / 'flow_template.html').read_text(encoding='utf-8')


def build_html(seqs, title, export_date):
    return (
        _TEMPLATE
        .replace('{TITLE}',       htmllib.escape(title))
        .replace('{EXPORT_DATE}', htmllib.escape(export_date))
        .replace('{SEQS_JSON}',   json.dumps(seqs, ensure_ascii=False))
    )


# ── Main ──────────────────────────────────────────────────────────────────────

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
    log.info('DataStage XML → Sequencer Flow gestart')

    xml_path = ds.find_xml_file()
    content  = ds.read_xml(xml_path)

    try:
        _root = ET.fromstring(content)
    except ET.ParseError as e:
        log.error("XML kan niet worden geparsed: %s", e)
        sys.exit(1)

    ds.validate_dse(_root, xml_path)

    _header     = _root.find('Header')
    export_date = _header.get('Date', '?') if _header is not None else _root.get('Date', '?')
    log.info('Export datum: %s', export_date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log.info('Sequencers/jobs parsen...')
    seqs = parse_all(content, export_date, xml_path.stem)

    for s in seqs:
        log.info('  %-50s  %d nodes  %d links',
                 s['id'], len(s['nodes']), len(s['links']))

    title       = xml_path.stem.replace('_', ' ').title()
    html_out    = build_html(seqs, title, export_date)
    output_path = OUTPUT_DIR / f'{xml_path.stem}_Flow.html'
    output_path.write_text(html_out, encoding='utf-8')

    log.info('─' * 60)
    log.info('Flow diagram klaar: %s', output_path.name)
    log.info('  Sequencers      : %d', len(seqs))
    log.info('  Bestandsgrootte : %d bytes', output_path.stat().st_size)
    log.info('─' * 60)


if __name__ == '__main__':
    main()
