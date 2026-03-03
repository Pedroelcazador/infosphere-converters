#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""IBM DataStage DSExport XML → Markdown converter"""

import re, html, sys, logging
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'ds_convert.log'

sys.path.insert(0, str(ROOT_DIR))
from md_to_html import md_to_html

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── Bestand zoeken & valideren ───────────────────────────────────────────────

def make_anchor(text: str) -> str:
    """Genereer een HTML anchor-naam die overeenkomt met de inhoudsopgave-links."""
    return re.sub(r'[^a-z0-9\-]', '', text.lower().replace(' ', '-').replace('_', '-'))


def find_xml_file():
    xml_files = list(INPUT_DIR.glob('*.xml'))
    if not xml_files:
        log.error("Geen XML bestand gevonden in %s", INPUT_DIR)
        log.error("Leg één DataStage DSExport XML bestand in de input/ map en probeer opnieuw.")
        sys.exit(1)
    if len(xml_files) > 1:
        log.error("Meer dan één XML bestand gevonden: %s", ', '.join(f.name for f in xml_files))
        log.error("Zorg dat er precies één XML bestand in de input/ map staat.")
        sys.exit(1)
    log.info("XML bestand gevonden: %s", xml_files[0].name)
    return xml_files[0]

def read_xml(path):
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc, errors='strict') as f:
                return f.read()
        except (UnicodeDecodeError, Exception):
            continue
    log.error("Kan %s niet lezen", path.name); sys.exit(1)

def validate_dse(content, xml_path):
    errors = []
    if '<DSExport' not in content:
        errors.append("Geen <DSExport> root element — dit lijkt geen DataStage export.")
    has_jobs = bool(re.search(r'<Job Identifier=', content))
    has_containers = bool(re.search(r'<SharedContainer Identifier=', content))
    if not has_jobs and not has_containers:
        errors.append("Geen <Job> of <SharedContainer> elementen — mogelijk LDM datamodel of ander formaat.")
    if 'logicalModelElement' in content:
        errors.append("logicalModelElement gevonden — gebruik de LDM converter.")
    if errors:
        for e in errors: log.error("Validatiefout: %s", e)
        log.error("Conversie afgebroken voor: %s", xml_path.name); sys.exit(1)
    n_jobs = len(re.findall(r'<Job Identifier=', content))
    n_ctr  = len(re.findall(r'<SharedContainer Identifier=', content))
    log.info("Validatie geslaagd — %d jobs, %d shared containers", n_jobs, n_ctr)


# ── Hulpfuncties ─────────────────────────────────────────────────────────────

def prop(text, name):
    """Haal een <Property Name="..."> waarde op."""
    m = re.search(rf'<Property Name="{re.escape(name)}"[^>]*>(.*?)</Property>', text, re.DOTALL)
    if not m: return ''
    val = re.sub(r'^\s*<!\[CDATA\[(.*?)\]\]>\s*$', r'\1', m.group(1).strip(), flags=re.DOTALL)
    return val.strip()

def xprop(tree, *tags):
    """Haal een waarde op uit een XMLProperties ElementTree via tag-naam(en)."""
    for tag in tags:
        for elem in tree.iter():
            t = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if t == tag and elem.text and elem.text.strip():
                return elem.text.strip()
    return ''

def get_xmlprops_tree(rec_body):
    """Haal XMLProperties op uit een CustomStage record en parse als XML tree."""
    for sub in re.finditer(r'<SubRecord>(.*?)</SubRecord>', rec_body, re.DOTALL):
        sb = sub.group(1)
        n = re.search(r'<Property Name="Name"[^>]*>(.*?)</Property>', sb)
        if not n or n.group(1).strip() != 'XMLProperties': continue
        v = re.search(r'<Property Name="Value"[^>]*>(.*?)</Property>', sb, re.DOTALL)
        if not v: continue
        raw = html.unescape(v.group(1).strip())
        try:
            return ET.fromstring(raw)
        except ET.ParseError:
            return None
    return None

def conditiontype_label(v):
    return {'0':'onvoorwaardelijk','2':'OK','4':'NOK'}.get(v, v)

def writemode_label(wm):
    return {'0':'INSERT','1':'UPDATE','6':'BULK LOAD','9':'UPSERT/MERGE'}.get(wm, f'onbekend ({wm})')

def skipindexes_label(v):
    return {'0':'geen','1':'unieke indexes uitgeschakeld','2':'alle indexes uitgeschakeld'}.get(v, v)

def parse_description(desc):
    lines = (desc or '').strip().splitlines()
    func_lines, hist_lines, in_hist = [], [], False
    date_re = re.compile(r'^\d{2}-\d{2}-\d{4}')
    for line in lines:
        if date_re.match(line.strip()): in_hist = True
        (hist_lines if in_hist else func_lines).append(line)
    func = '\n'.join(func_lines).strip()
    hist = []
    for line in hist_lines:
        line = line.strip()
        if not line: continue
        parts = line.split(None, 2)
        if len(parts) == 3 and date_re.match(parts[0]):
            hist.append((parts[0], parts[1], parts[2]))
        elif hist:
            hist[-1] = (hist[-1][0], hist[-1][1], hist[-1][2] + ' ' + line)
    return func, hist


# ── XML splitsen ─────────────────────────────────────────────────────────────

def split_jobs(content):
    """
    Geeft lijst van (job_id, job_type, job_body).
    JobType="1" = parallel, JobType="2" = sequencer.
    Valt terug op lege string als het attribuut ontbreekt.
    """
    results = []
    for m in re.finditer(r'<Job Identifier="([^"]+)"([^>]*?)>(.*?)</Job>', content, re.DOTALL):
        job_id    = m.group(1)
        attrs     = m.group(2)
        job_body  = m.group(3)
        jt = re.search(r'JobType="([^"]*)"', attrs)
        job_type  = jt.group(1) if jt else ''
        results.append((job_id, job_type, job_body))
    return results


def split_containers(content):
    """
    Extraheert SharedContainer blokken uit de volledige XML content.
    Geeft lijst van (container_name, date_modified, container_body).
    """
    containers = []
    for m in re.finditer(
        r'<SharedContainer Identifier="([^"]+)"([^>]*?)>(.*?)</SharedContainer>',
        content, re.DOTALL
    ):
        name       = m.group(1)
        attrs      = m.group(2)
        sc_body    = m.group(3)
        dm = re.search(r'DateModified="([^"]+)"', attrs)
        date_mod   = dm.group(1) if dm else '?'
        containers.append((name, date_mod, sc_body))
    return containers

def get_records(job_body):
    return {m.group(1): (m.group(2), m.group(3))
            for m in re.finditer(r'<Record Identifier="([^"]+)" Type="([^"]+)"[^>]*>(.*?)</Record>', job_body, re.DOTALL)}

def get_job_header(job_body, job_id):
    name = prop(job_body, 'Name') or job_id

    # Description + wijzigingshistorie zit in ROOT record
    root_m = re.search(r'<Record Identifier="ROOT"[^>]*>(.*?)</Record>', job_body, re.DOTALL)
    raw_desc = ''
    params   = []
    if root_m:
        rb       = root_m.group(1)
        raw_desc = prop(rb, 'Description') or prop(rb, 'FullDescription') or prop(rb, 'ShortDescription')
        raw_desc = html.unescape(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', raw_desc, flags=re.DOTALL)).strip()
        # Parameters uit SubRecords in ROOT
        for sub in re.finditer(r'<SubRecord>(.*?)</SubRecord>', rb, re.DOTALL):
            sb = sub.group(1)
            pname = prop(sb, 'Name')
            pdef  = prop(sb, 'Default') or prop(sb, 'DefaultValue')
            if not pname: continue
            if pname.startswith('$') or pname.startswith('par_'): continue
            if pdef in ('(As pre-defined)', ''): continue
            params.append((pname, pdef))

    func_desc, hist = parse_description(raw_desc)
    return name, func_desc, hist, params

def get_annotations(job_body):
    anns = []
    for m in re.finditer(r'<Record Identifier="[^"]+" Type="Annotation"[^>]*>(.*?)</Record>', job_body, re.DOTALL):
        body = m.group(1)
        # AnnotationType 0 = tekstannotatie, 1 = layout/lege annotatie
        ann_type = prop(body, 'AnnotationType')
        if ann_type == '1': continue
        txt = prop(body, 'AnnotationText')
        if not txt: continue
        txt = html.unescape(txt).strip()
        if txt:
            anns.append(txt)
    return anns


# ── Oracle Connector renderer ─────────────────────────────────────────────────

def detect_mode(rec_body):
    """TARGET als InputPins aanwezig en niet leeg."""
    m = re.search(r'<Property Name="InputPins"[^>]*>(.*?)</Property>', rec_body)
    if m and m.group(1).strip(): return 'TARGET'
    return 'SOURCE'

def render_oracle(stage_name, rec_body):
    xp   = get_xmlprops_tree(rec_body)
    mode = detect_mode(rec_body)
    lines = [f"\n### {stage_name} — OracleConnectorPX", f"**Type:** {mode}"]

    if xp is None:
        lines.append("*(XMLProperties konden niet worden geparsed)*")
        return '\n'.join(lines)

    if mode == 'TARGET':
        table    = xprop(xp, 'TableName')
        wm       = xprop(xp, 'WriteMode')
        array    = xprop(xp, 'ArraySize')
        rec_cnt  = xprop(xp, 'RecordCount')
        gen_sql  = xprop(xp, 'GenerateSQL')
        drop_unm = xprop(xp, 'DropUnmatchedFields')
        fail_err = xprop(xp, 'FailOnRowErrorPX')
        before   = xprop(xp, 'BeforeSQL', 'BeforeSQLStatement')
        after    = xprop(xp, 'AfterSQL',  'AfterSQLStatement')

        if table:   lines.append(f"**Tabel:** {table.lower()}")
        if wm:      lines.append(f"**Schrijfmodus:** {writemode_label(wm)}")

        if gen_sql:
            if gen_sql in ('1','true'):
                lines.append("**GenerateSQL:** ja *(DataStage genereert INSERT SQL automatisch op basis van kolomdefinitie)*")
            else:
                lines.append("**GenerateSQL:** nee *(handmatige SQL)*")

        if array:   lines.append(f"**ArraySize:** {array}")
        if rec_cnt: lines.append(f"**RecordCount:** {rec_cnt}")

        if drop_unm:
            if drop_unm in ('1','true'):
                lines.append("**DropUnmatchedFields:** ja *(kolommen zonder match in doeltabel worden genegeerd)*")
            else:
                lines.append("**DropUnmatchedFields:** nee ⚠️ *(kolommen zonder match veroorzaken een fout)*")

        if fail_err and fail_err not in ('1','true'):
            lines.append("**FailOnRowErrorPX:** nee *(rij-fouten worden genegeerd)*")

        # Bulk Load
        if wm == '6':
            parallel   = xprop(xp, 'DirectParallelism')
            buf_size   = xprop(xp, 'BufferSize')
            skip_idx   = xprop(xp, 'SkipIndexes')
            redo       = xprop(xp, 'NoLog')
            date_cache = xprop(xp, 'DateCacheSize')
            rebuild    = xprop(xp, 'RebuildIndexes')
            lines.append("")
            lines.append("**LoadControl:**")
            if parallel and parallel != '0': lines.append("- Parallel load sessions: ja")
            if buf_size:  lines.append(f"- Buffer: {buf_size} KB")
            if skip_idx:  lines.append(f"- Indexes: {skipindexes_label(skip_idx)}")
            if redo:
                lines.append(f"- Redo log: {'uitgeschakeld' if redo in ('1','true') else 'actief'}")
            if date_cache and date_cache != '0':
                lines.append(f"- Date cache: actief (size: {date_cache})")
            if rebuild and rebuild in ('1','true'):
                lines.append("- Na load: indexes herbouwen (PARALLEL / NOLOGGING)")

        if before: lines += ["#### Before SQL\n", f"```sql\n{before}\n```\n"]
        if after:  lines += ["#### After SQL\n",  f"```sql\n{after}\n```\n"]

    else:  # SOURCE
        gen_sql    = xprop(xp, 'GenerateSQL')
        sql        = xprop(xp, 'SelectStatement', 'UserDefinedSQL', 'TableName')
        array      = xprop(xp, 'ArraySize')
        rec_cnt    = xprop(xp, 'RecordCount')
        prefetch_r = xprop(xp, 'PrefetchRowCount')
        prefetch_m = xprop(xp, 'PrefetchMemorySize')
        where_sql  = xprop(xp, 'WhereClause')
        part_read  = xprop(xp, 'PartitionedReads')

        if gen_sql:
            if gen_sql in ('1','true'):
                lines.append("**GenerateSQL:** ja *(DataStage genereert SELECT SQL automatisch)*")
            else:
                lines.append("**GenerateSQL:** nee *(handmatige SQL)*")

        if array:      lines.append(f"**ArraySize:** {array}")
        if rec_cnt:    lines.append(f"**RecordCount:** {rec_cnt}")
        if prefetch_r: lines.append(f"**PrefetchRowCount:** {prefetch_r}")
        if prefetch_m: lines.append(f"**PrefetchMemorySize:** {prefetch_m} KB")
        if part_read and part_read in ('1','true'):
            lines.append("**Partitioned reads:** ja (hash-partitionering)")

        if sql: lines += ["#### SQL\n", f"```sql\n{sql}\n```\n"]
        if where_sql: lines += ["#### Where clause\n", f"```sql\n{where_sql}\n```\n"]

    return '\n'.join(lines)


# ── Job header blok ───────────────────────────────────────────────────────────

SKIP_TYPES = {
    'JobDefn','ContainerDefn','ContainerView',
    'CustomInput','CustomOutput',
    'TrxInput','TrxOutput',
    'StdOutput','StdPin',
    'Annotation','TextAnnotation',
}

# ── Px stage property helpers ─────────────────────────────────────────────────

def get_custom_props(rec_body):
    """Geeft dict van alle CustomProperty name→value paren."""
    props = {}
    for sub in re.finditer(r'<SubRecord>(.*?)</SubRecord>', rec_body, re.DOTALL):
        sb = sub.group(1)
        n = re.search(r'<Property Name="Name"[^>]*>(.*?)</Property>', sb)
        v = re.search(r'<Property Name="Value"[^>]*>(.*?)</Property>', sb, re.DOTALL)
        if n and v:
            props[n.group(1).strip()] = v.group(1).strip()
    return props

def parse_px_keys(key_str):
    """
    Parset de DataStage \\(3)key\\(2)VELDNAAM\\(2) notatie.
    Geeft lijst van (veldnaam, richting) tuples; richting is 'asc'/'desc' of ''.
    """
    keys = []
    for m in re.finditer(r'\\\(3\)key\\\(2\)([^\\]+)\\\(2\)', key_str):
        field = m.group(1).strip()
        after_pos = m.end()
        dir_m = re.search(
            r'\\\(3\)\\\(3\)asc\\\\desc\\\(2\)(asc|desc)\\\(2\)',
            key_str[after_pos:after_pos+80]
        )
        direction = dir_m.group(1) if dir_m else ''
        keys.append((field, direction))
    return keys

def parse_px_reduce(reduce_str):
    """Parset PxAggregator reduce-string naar lijst van (veld, functie) tuples."""
    result = []
    seen = set()
    for m in re.finditer(r'\\\(3\)reduce\\\(2\)([^\\]+)\\\(2\)', reduce_str):
        field = m.group(1).strip()
        if field in seen: continue
        seen.add(field)
        after = m.end()
        func_m = re.search(
            r'\\\(3\)\\\(3\)([^\\]+)\\\(2\)' + re.escape(field) + r'\\\(2\)',
            reduce_str[after:after+80]
        )
        func = func_m.group(1).strip() if func_m else '?'
        if func == 'preserveType': continue
        result.append((field, func))
    return result

def parse_px_modifyspec(spec_str):
    """Parset PxModify modifyspec naar lijst van operaties."""
    ops = []
    for m in re.finditer(r'\\\(3\)modifyspec\\\(2\)([^\\]+)\\\(2\)', spec_str):
        op = m.group(1).strip()
        if op and op != 'DROP':
            ops.append(op)
    return ops

def render_pxjoin(stage_name, rec_body):
    cprops = get_custom_props(rec_body)
    operator = cprops.get('operator', '').lower()
    key_str  = cprops.get('key', '')
    keys = parse_px_keys(key_str)
    # Mooiere naam voor join type
    labels = {
        'innerjoin': 'Inner Join', 'leftouterjoin': 'Left Outer Join',
        'rightouterjoin': 'Right Outer Join', 'fullouterjoin': 'Full Outer Join',
    }
    op_label = labels.get(operator, operator or '?')
    lines = [f"\n### {stage_name} — Join", f"**Type:** {op_label}"]
    n_inputs = len([p for p in prop(rec_body, 'InputPins').split('|') if p.strip()])
    if n_inputs > 2:
        lines.append(f"**Inputs:** {n_inputs} links")
    if keys:
        key_parts = [f"`{f}` {d}".strip() for f, d in keys]
        lines.append(f"**Sleutelveld(en):** {', '.join(key_parts)}")
    lines.append("")
    return '\n'.join(lines)


def render_pxagg(stage_name, rec_body):
    cprops = get_custom_props(rec_body)
    method    = cprops.get('method', '')
    key_str   = cprops.get('key', '')
    reduce_str = cprops.get('reduce', '')
    keys    = parse_px_keys(key_str)
    reduces = parse_px_reduce(reduce_str)
    lines = [f"\n### {stage_name} — Aggregator"]
    if method: lines.append(f"**Methode:** {method}")
    if keys:
        key_parts = [f"`{f}`" for f, _ in keys]
        lines.append(f"**Groepeersleutel(s):** {', '.join(key_parts)}")
    if reduces:
        lines.append("**Aggregaties:**")
        for field, func in reduces:
            lines.append(f"- `{field}`: {func.upper()}")
    lines.append("")
    return '\n'.join(lines)


def render_pxsort(stage_name, rec_body):
    cprops = get_custom_props(rec_body)
    key_str = cprops.get('key', '')
    keys = parse_px_keys(key_str)
    lines = [f"\n### {stage_name} — Sort"]
    if keys:
        parts = [f"`{f}` {d}".strip() for f, d in keys]
        lines.append(f"**Sorteersleutel(s):** {', '.join(parts)}")
    lines.append("")
    return '\n'.join(lines)


def render_pxmodify(stage_name, rec_body):
    cprops = get_custom_props(rec_body)
    spec_str = cprops.get('modifyspec', '')
    ops = parse_px_modifyspec(spec_str)
    lines = [f"\n### {stage_name} — Modify"]
    if ops:
        lines.append("**Operaties:**")
        for op in ops:
            lines.append(f"- `{op}`")
    lines.append("")
    return '\n'.join(lines)


def render_containerstage(stage_name, rec_body):
    container_name = prop(rec_body, 'ContainerName') or '?'
    lines = [f"\n### {stage_name} — Container", f"**Gebruikt container:** `{container_name}`", ""]
    return '\n'.join(lines)


def render_job_header_block(job_id, job_body, date_modified, time_modified):
    name, func_desc, hist, params = get_job_header(job_body, job_id)
    anns = get_annotations(job_body)

    anchor = make_anchor(job_id)
    out = [f'\n<a name="{anchor}"></a>', f"# {name}\n", f"**Beschrijving:** {func_desc or '—'}\n"]

    if hist:
        out += ["**Wijzigingshistorie:**\n", "| Datum | Auteur | Omschrijving |", "|-------|--------|--------------|"]
        for d, a, o in hist: out.append(f"| {d} | {a} | {o} |")
        out.append("")

    line = f"**Laatste wijziging:** {date_modified} {time_modified}"
    if params:
        ps = ', '.join(f"{p} (default: {d})" for p, d in params)
        out.append(line)
        out.append(f"**Parameters:** {ps}")
    else:
        out.append(line)
    out.append("")

    for ann in anns:
        if ann.strip():
            out.append(f"*{ann}*\n")

    return out


# ── Parallel job renderer ─────────────────────────────────────────────────────

def render_container(container_name, sc_body, date_modified='?'):
    """Rendert een SharedContainer als een parallel job sectie."""
    # Haal de ContainerDefn metadata op
    defn_m = re.search(r'<Record Identifier="ROOT" Type="ContainerDefn"[^>]*>(.*?)</Record>', sc_body, re.DOTALL)
    raw_desc = ''
    if defn_m:
        defn_body = defn_m.group(1)
        raw_desc = prop(defn_body, 'Description') or prop(defn_body, 'FullDescription') or ''
        raw_desc = html.unescape(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', raw_desc, flags=re.DOTALL)).strip()

    func_desc, hist = parse_description(raw_desc)
    anchor = make_anchor(container_name)
    out = [f'\n<a name="{anchor}"></a>', f"# {container_name}\n",
           f"**Beschrijving:** {func_desc or '—'}\n"]

    if hist:
        out += ["**Wijzigingshistorie:**\n", "| Datum | Auteur | Omschrijving |", "|-------|--------|--------------|"]
        for d, a, o in hist: out.append(f"| {d} | {a} | {o} |")
        out.append("")

    out.append(f"**Laatste wijziging:** {date_modified}\n")

    # Annotaties
    anns = get_annotations(sc_body)
    for ann in anns:
        if ann.strip():
            out.append(f"*{ann}*\n")

    out.append("## Stages\n")
    records = get_records(sc_body)

    for rec_id, (rec_type, rec_body) in records.items():
        if rec_type in SKIP_TYPES: continue
        stage_name = prop(rec_body, 'Name') or rec_id
        stage_type = prop(rec_body, 'StageType') or rec_type

        if stage_type == 'OracleConnectorPX' or rec_type == 'PxOracleConnector':
            out.append(render_oracle(stage_name, rec_body))
        elif stage_type in ('PxTransformer', 'Transformer') or rec_type == 'TransformerStage':
            trx = prop(rec_body, 'TransformCode') or ''
            out.append(f"\n### {stage_name} — Transformer")
            if trx: out.append(f"```\n{trx}\n```")
            out.append("")
        elif stage_type == 'PxJoin':
            out.append(render_pxjoin(stage_name, rec_body))
        elif stage_type == 'PxAggregator':
            out.append(render_pxagg(stage_name, rec_body))
        elif stage_type == 'PxSort':
            out.append(render_pxsort(stage_name, rec_body))
        elif stage_type == 'PxModify':
            out.append(render_pxmodify(stage_name, rec_body))
        elif stage_type in ('PxRemDup',):
            out.append(f"\n### {stage_name} — Remove Duplicates\n")
        elif stage_type in ('PxCopy',):
            out.append(f"\n### {stage_name} — Copy (fan-out)\n")
        elif stage_type in ('PxLookup',):
            out.append(f"\n### {stage_name} — Lookup\n")
        elif rec_type == 'ContainerStage':
            out.append(render_containerstage(stage_name, rec_body))
        elif rec_type not in SKIP_TYPES:
            out.append(f"\n### {stage_name} — {stage_type}\n")

    return '\n'.join(out)


def render_parallel_job(job_id, job_body, date_modified, time_modified):
    out = render_job_header_block(job_id, job_body, date_modified, time_modified)
    records = get_records(job_body)
    out.append("## Stages\n")

    for rec_id, (rec_type, rec_body) in records.items():
        if rec_type in SKIP_TYPES: continue
        stage_name = prop(rec_body, 'Name') or rec_id
        stage_type = prop(rec_body, 'StageType') or rec_type

        if stage_type == 'OracleConnectorPX' or rec_type == 'PxOracleConnector':
            out.append(render_oracle(stage_name, rec_body))
        elif stage_type in ('PxTransformer', 'Transformer') or rec_type == 'TransformerStage':
            trx = prop(rec_body, 'TransformCode') or ''
            out.append(f"\n### {stage_name} — Transformer")
            if trx: out.append(f"```\n{trx}\n```")
            out.append("")
        elif stage_type == 'PxJoin':
            out.append(render_pxjoin(stage_name, rec_body))
        elif stage_type == 'PxAggregator':
            out.append(render_pxagg(stage_name, rec_body))
        elif stage_type == 'PxSort':
            out.append(render_pxsort(stage_name, rec_body))
        elif stage_type == 'PxModify':
            out.append(render_pxmodify(stage_name, rec_body))
        elif stage_type in ('PxRemDup',):
            out.append(f"\n### {stage_name} — Remove Duplicates\n")
        elif stage_type in ('PxCopy',):
            out.append(f"\n### {stage_name} — Copy (fan-out)\n")
        elif stage_type in ('PxLookup',):
            out.append(f"\n### {stage_name} — Lookup\n")
        elif stage_type in ('PxPeek', 'Peek'):
            xp  = get_xmlprops_tree(rec_body)
            out.append(f"\n### {stage_name} — Peek")
            if xp is not None:
                cnt = xprop(xp, 'RecordCount')
                fn  = xprop(xp, 'FileName', 'Filename')
                if cnt: out.append(f"**Recordcount:** {cnt}")
                if fn:  out.append(f"**Bestand:** `{fn}`")
            out.append("")
        elif rec_type == 'ContainerStage':
            out.append(render_containerstage(stage_name, rec_body))
        elif rec_type not in SKIP_TYPES:
            out.append(f"\n### {stage_name} — {stage_type}\n")

    return '\n'.join(out)


# ── Sequencer job renderer ────────────────────────────────────────────────────

def render_sequencer_job(job_id, job_body, date_modified, time_modified):
    out = render_job_header_block(job_id, job_body, date_modified, time_modified)
    records = get_records(job_body)
    out.append("## Uitvoeringsvolgorde\n")

    id_to_name = {rid: (prop(rb, 'Name') or rid) for rid, (_, rb) in records.items()}
    step = 1

    for rec_id, (rec_type, rec_body) in records.items():
        rec_name = prop(rec_body, 'Name') or rec_id

        if rec_type == 'JSJobActivity':
            jobname = prop(rec_body, 'Jobname') or rec_name
            out.append(f"### Stap {step}: {rec_name}"); step += 1
            out.append(f"**Aanroept job:** `{jobname}`")

            param_vals = []
            for sub in re.finditer(r'<SubRecord>(.*?)</SubRecord>', rec_body, re.DOTALL):
                sb = sub.group(1)
                pn = prop(sb, 'Name'); pv = prop(sb, 'DisplayValue')
                if not pn or not pv: continue
                if pn.startswith('$'): continue
                if pv in ('#uvr_Info.uvJobname#_#uvr_Info.uvSchemaPostfix#','(As pre-defined)'): continue
                param_vals.append(f"{pn}={pv}")
            if param_vals: out.append(f"**Parameters:** {', '.join(param_vals)}")

            for pin_id in prop(rec_body, 'OutputPins').split('|'):
                pin_id = pin_id.strip()
                if pin_id not in records: continue
                _, pb = records[pin_id]
                partner   = prop(pb, 'Partner')
                condition = prop(pb, 'ConditionType')
                pid = partner.split('|')[0] if partner else ''
                out.append(f"**Bij {conditiontype_label(condition)}:** → {id_to_name.get(pid, pid)}")
            out.append("")

        elif rec_type == 'JSSequencer':
            seq_type = prop(rec_body, 'SequencerType')
            gate = ('AND-gate (wacht op alle inputs)' if seq_type == '1' else
                    'OR-gate (gaat door bij eerste input)' if seq_type == '0' else seq_type)
            input_names = []
            for pin_id in prop(rec_body, 'InputPins').split('|'):
                pin_id = pin_id.strip()
                if pin_id in records:
                    _, pb = records[pin_id]; input_names.append(prop(pb, 'Name') or pin_id)
            next_steps = []
            for pin_id in prop(rec_body, 'OutputPins').split('|'):
                pin_id = pin_id.strip()
                if pin_id not in records: continue
                _, pb = records[pin_id]
                partner = prop(pb, 'Partner')
                pid = partner.split('|')[0] if partner else ''
                next_steps.append(id_to_name.get(pid, pid))

            out.append(f"### Synchronisatiepunt: {rec_name}")
            out.append(f"**Type:** {gate}")
            if input_names: out.append(f"**Wacht op:** {', '.join(input_names)}")
            if next_steps:  out.append(f"**Daarna:** → {', '.join(next_steps)}")
            out.append("")

    return '\n'.join(out)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("DataStage XML → Markdown converter gestart")

    xml_path = find_xml_file()
    content  = read_xml(xml_path)
    validate_dse(content, xml_path)

    hm          = re.search(r'<Header[^>]+Date="([^"]+)"', content)
    export_date = hm.group(1) if hm else '?'
    jobs        = split_jobs(content)
    log.info("Jobs verwerken: %d totaal", len(jobs))

    parallel_jobs, sequencer_jobs = [], []
    for job_id, job_type, job_body in jobs:
        dm = re.search(rf'<Job Identifier="{re.escape(job_id)}"[^>]*DateModified="([^"]+)"', content)
        tm = re.search(rf'<Job Identifier="{re.escape(job_id)}"[^>]*TimeModified="([^"]+)"', content)
        date_mod = dm.group(1) if dm else '?'
        time_mod = tm.group(1) if tm else '?'

        # JobType="2" = sequencer, JSJobActivity = sequencer stap
        is_seq = job_type == '2' or bool(re.search(r'Type="JSJobActivity"', job_body))
        if is_seq:
            sequencer_jobs.append((job_id, job_body, date_mod, time_mod))
        else:
            parallel_jobs.append((job_id, job_body, date_mod, time_mod))

    # Shared containers (buiten Job blokken)
    container_jobs = split_containers(content)
    for cname, *_ in container_jobs:
        log.info("  Container : %s", cname)

    ts    = datetime.now().strftime('%d-%m-%Y %H:%M')
    title = xml_path.stem.replace('_', ' ').title()
    lines = [f"# DataStage Jobs — {title}\n",
             f"*Gegenereerd op {ts} uit XML-export d.d. {export_date}*\n",
             "## Inhoudsopgave\n"]

    if sequencer_jobs:
        lines.append("### Sequencer-jobs\n")
        for jid, *_ in sequencer_jobs:
            lines.append(f"- [{jid}](#{make_anchor(jid)})")

    lines.append("\n### Parallel jobs\n")
    for jid, *_ in parallel_jobs:
        lines.append(f"- [{jid}](#{make_anchor(jid)})")

    if container_jobs:
        lines.append("\n### Generieke containers\n")
        for cname, *_ in container_jobs:
            lines.append(f"- [{cname}](#{make_anchor(cname)})")

    lines.append("\n---\n")

    if sequencer_jobs:
        lines.append("# Sequencer-jobs\n")
        for job_id, job_body, dm, tm in sequencer_jobs:
            log.info("  Sequencer: %s", job_id)
            lines.append(render_sequencer_job(job_id, job_body, dm, tm))
            lines.append("\n---\n")

    lines.append("# Parallel jobs\n")
    for job_id, job_body, dm, tm in parallel_jobs:
        log.info("  Parallel : %s", job_id)
        lines.append(render_parallel_job(job_id, job_body, dm, tm))
        lines.append("\n---\n")

    if container_jobs:
        lines.append("# Generieke containers\n")
        for cname, date_mod, sc_body in container_jobs:
            lines.append(render_container(cname, sc_body, date_mod))
            lines.append("\n---\n")

    md_text     = '\n'.join(lines)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{xml_path.stem}_DataStage.md"
    output_path.write_text(md_text, encoding='utf-8')

    html_path = OUTPUT_DIR / f"{xml_path.stem}_DataStage.html"
    html_title = f"DataStage Jobs — {title}"
    html_path.write_text(md_to_html(md_text, title=html_title), encoding='utf-8')

    log.info("─" * 60)
    log.info("Conversie geslaagd: %s", xml_path.name)
    log.info("  Parallel jobs   : %d", len(parallel_jobs))
    log.info("  Sequencer jobs  : %d", len(sequencer_jobs))
    log.info("  Containers      : %d", len(container_jobs))
    log.info("  Totaal          : %d", len(parallel_jobs) + len(sequencer_jobs) + len(container_jobs))
    log.info("  Markdown output : %s (%d bytes)", output_path.name, output_path.stat().st_size)
    log.info("  HTML output     : %s (%d bytes)", html_path.name, html_path.stat().st_size)
    log.info("─" * 60)

if __name__ == '__main__':
    main()
