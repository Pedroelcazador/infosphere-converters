#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""IBM DataStage DSExport XML → interactieve Sequencer Flowchart (HTML)

Genereert een standalone HTML met een interactieve flowchart per sequencer-job.
Per sequencer: alle activiteiten als nodes, OK/NOK/onvoorwaardelijk paden als
gekleurde verbindingen. Klik op een job-activiteit om SQL en tabel-details te zien.

Gebruik: leg één DSExport XML in de map en draai `python3 ds_flow.py`
Output : <bestandsnaam>_Flow.html  +  ds_flow.log
"""

import re, html as htmllib, sys, logging, json
from collections import deque
from pathlib import Path

sys.modules.pop('ds_convert', None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ds_convert'))
import ds_convert as ds

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = SCRIPT_DIR / 'ds_flow.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler(sys.stdout)],
)
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

def extract_par_details(job_body):
    records = {
        m.group(1): (m.group(2), m.group(3))
        for m in re.finditer(
            r'<Record Identifier="([^"]+)" Type="([^"]+)"[^>]*>(.*?)</Record>',
            job_body, re.DOTALL)
    }
    stages = []
    for rid, (rtype, rbody) in records.items():
        stage_type = ds.prop(rbody, 'StageType') or rtype
        if stage_type != 'OracleConnectorPX':
            continue
        name = ds.prop(rbody, 'Name') or rid
        mode = 'TARGET' if ds.prop(rbody, 'InputPins') else 'SOURCE'
        xp   = ds.get_xmlprops_tree(rbody)
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


# ── Sequencer parsen ──────────────────────────────────────────────────────────

def parse_sequencer(job_id, job_body, par_bodies):
    records = {
        m.group(1): (m.group(2), m.group(3))
        for m in re.finditer(
            r'<Record Identifier="([^"]+)" Type="([^"]+)"[^>]*>(.*?)</Record>',
            job_body, re.DOTALL)
    }

    # Beschrijving uit ROOT
    desc = ''
    root_m = re.search(r'<Record Identifier="ROOT"[^>]*>(.*?)</Record>', job_body, re.DOTALL)
    if root_m:
        raw = ds.prop(root_m.group(1), 'Description') or ''
        raw = htmllib.unescape(
            re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', raw, flags=re.DOTALL)).strip()
        func_desc, _ = ds.parse_description(raw)
        desc = func_desc or ''

    # pin → stage map
    pin_to_stage = {}
    for rid, (rtype, rbody) in records.items():
        for pid in (ds.prop(rbody, 'InputPins') + '|' + ds.prop(rbody, 'OutputPins')).split('|'):
            pid = pid.strip()
            if pid:
                pin_to_stage[pid] = rid

    # Links via output-pin Partners (dedupliceer op from/to/cond)
    links   = []
    seen_lk = set()
    for rid, (rtype, rbody) in records.items():
        if rtype not in ('JSActivityOutput', 'CActivityOutput', 'StdOutput'):
            continue
        partner = ds.prop(rbody, 'Partner')
        if not partner:
            continue
        target  = partner.split('|')[0]
        source  = pin_to_stage.get(rid)
        if not source or source == target:
            continue
        cond = ds.prop(rbody, 'ConditionType')
        name = ds.prop(rbody, 'Name') or ''
        key  = (source, target, cond)
        if key in seen_lk:
            continue
        seen_lk.add(key)
        links.append({'from': source, 'to': target, 'cond': cond, 'name': name})

    # Nodes
    nodes = {}
    for rid, (rtype, rbody) in records.items():
        if rtype in SKIP_SEQ:
            continue
        name    = ds.prop(rbody, 'Name') or rid
        kind    = RTYPE_KIND.get(rtype, 'other')
        jobname = ds.prop(rbody, 'Jobname') or ''
        gate    = ''
        if kind == 'sync':
            st   = ds.prop(rbody, 'SequencerType')
            gate = 'AND' if st == '1' else 'OR' if st == '0' else '?'

        par_stages = []
        if kind == 'job' and jobname and jobname in par_bodies:
            par_stages = extract_par_details(par_bodies[jobname])

        nodes[rid] = {
            'id': rid, 'name': name, 'kind': kind,
            'rtype': rtype, 'jobname': jobname,
            'gate': gate, 'par_stages': par_stages,
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

def parse_all(content):
    jobs_raw = list(re.finditer(
        r'<Job Identifier="([^"]+)"([^>]*?)>(.*?)</Job>', content, re.DOTALL))

    par_bodies = {}
    for jm in jobs_raw:
        jid = jm.group(1)
        if not jid.startswith('seq_'):
            par_bodies[jid] = jm.group(3)

    sequencers = []
    for jm in jobs_raw:
        jid      = jm.group(1)
        job_body = jm.group(3)
        if not jid.startswith('seq_'):
            continue
        rtypes = re.findall(r'Type="([^"]+)"', job_body)
        if not any(r in ('JSJobActivity','CJobActivity','JSSequencer','CSequencer')
                   for r in rtypes):
            continue
        log.info('  Sequencer: %s', jid)
        sequencers.append(parse_sequencer(jid, job_body, par_bodies))

    # Fallback: geen sequencers → toon parallel jobs als simpele nodes
    if not sequencers:
        log.info('  Geen sequencers gevonden — parallel jobs als overzicht weergeven')
        nodes = []
        for jid, body in par_bodies.items():
            par_stages = extract_par_details(body)
            root_m = re.search(r'<Record Identifier="ROOT"[^>]*>(.*?)</Record>', body, re.DOTALL)
            desc = ''
            if root_m:
                raw = ds.prop(root_m.group(1), 'Description') or ''
                raw = htmllib.unescape(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', raw, flags=re.DOTALL)).strip()
                func_desc, _ = ds.parse_description(raw)
                desc = func_desc or ''
            nodes.append({
                'id': jid, 'name': jid, 'kind': 'job',
                'rtype': 'JSJobActivity', 'jobname': jid,
                'gate': '', 'par_stages': par_stages,
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

def build_html(seqs, title, export_date):
    seqs_json = json.dumps(seqs, ensure_ascii=False)
    title_esc = htmllib.escape(title)

    css = """
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --bg:#f4f6f8;--surf:#ffffff;--surf2:#f0f2f5;--border:#d0d7de;
  --text:#1f2328;--muted:#656d76;--accent:#0969da;--accent2:#0550ae;
  --ok:#1a7f37;--nok:#cf222e;--warn:#9a6700;--cond:#6e40c9;
  --radius:9px;--tbh:52px;--panw:380px;
}
body{background:var(--bg);color:var(--text);
     font-family:'Segoe UI',system-ui,sans-serif;overflow:hidden;height:100vh;}
#toolbar{
  position:fixed;top:0;left:0;right:0;height:var(--tbh);z-index:300;
  background:#fff;border-bottom:1px solid var(--border);
  display:flex;align-items:center;box-shadow:0 1px 3px rgba(0,0,0,.08);
}
#uwv-logo{
  flex-shrink:0;width:var(--tbh);height:var(--tbh);background:var(--accent);
  display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:900;color:#fff;letter-spacing:-.5px;
}
#toolbar-title{padding:0 16px;font-size:13px;color:var(--muted);flex:1;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
#toolbar-title strong{color:var(--text);}
#seq-tabs{display:flex;height:100%;overflow-x:auto;flex-shrink:0;max-width:580px;}
#seq-tabs::-webkit-scrollbar{height:3px;}
#seq-tabs::-webkit-scrollbar-thumb{background:#d0d7de;}
.stab{
  height:100%;padding:0 16px;border:none;background:transparent;
  color:var(--muted);font-size:12px;font-weight:500;cursor:pointer;
  border-bottom:2px solid transparent;white-space:nowrap;transition:all .15s;flex-shrink:0;
}
.stab:hover{color:var(--text);}
.stab.active{color:var(--accent);border-bottom-color:var(--accent);}
#toolbar-right{padding:0 12px;display:flex;gap:6px;flex-shrink:0;}
.tbtn{
  padding:5px 11px;border-radius:6px;border:1px solid var(--border);
  background:var(--surf);color:var(--text);font-size:11.5px;cursor:pointer;
}
.tbtn:hover{background:var(--surf2);}
#canvas-wrap{
  position:fixed;top:var(--tbh);left:0;right:0;bottom:0;overflow:hidden;
  background:var(--bg);
}
#canvas{position:absolute;top:0;left:0;transform-origin:0 0;}
.node{
  position:absolute;border-radius:var(--radius);border:1.5px solid var(--border);
  background:var(--surf);cursor:pointer;
  transition:border-color .15s,box-shadow .12s,transform .1s;
  min-width:148px;max-width:185px;padding:10px 13px;
  box-shadow:0 1px 4px rgba(0,0,0,.1),0 2px 8px rgba(0,0,0,.06);
}
.node:hover{
  border-color:var(--accent);transform:translateY(-2px);
  box-shadow:0 0 0 2px rgba(9,105,218,.15),0 4px 14px rgba(0,0,0,.12);
}
.node.selected{
  border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(9,105,218,.2),0 4px 18px rgba(0,0,0,.14);
}
.node.kind-job{background:#fff;border-color:#b6d4fb;}
.node.kind-job.has-details{border-color:#0969da;border-width:1.5px;}
.node.kind-sync{
  background:#faf8ff;border-color:#c8b8f5;
  min-width:110px;max-width:150px;padding:8px 12px;
}
.node.kind-stop{background:#fff5f5;border-color:#f5b8b8;min-width:110px;}
.node.kind-vars,.node.kind-routine,.node.kind-exec{
  background:var(--surf2);border-color:#d0d7de;
  min-width:110px;max-width:160px;padding:8px 12px;
}
.node.kind-loop_start,.node.kind-loop_end{
  background:#f0fff4;border-color:#9be9b0;min-width:110px;
}
.node.kind-exception{background:#fff8f0;border-color:#f5c97a;}
.node.kind-condition{background:#fdf8ff;border-color:#d2b4f5;}
.node-icon{font-size:17px;margin-bottom:4px;line-height:1;}
.node-name{font-size:11px;font-weight:700;color:var(--text);line-height:1.35;word-break:break-word;}
.node-sub{font-size:9.5px;color:var(--muted);margin-top:3px;}
.node-badge{
  display:inline-block;margin-top:5px;padding:2px 8px;border-radius:10px;
  font-size:9px;font-weight:700;
}
.badge-job{background:#dbeafe;color:#1d4ed8;}
.badge-and{background:#ede9fe;color:#6d28d9;}
.badge-or{background:#dcfce7;color:#166534;}
.badge-stop{background:#fee2e2;color:#991b1b;}
#detail-panel{
  position:fixed;top:var(--tbh);right:0;width:var(--panw);
  height:calc(100vh - var(--tbh));
  background:var(--surf);border-left:1px solid var(--border);
  transform:translateX(100%);transition:transform .2s ease;
  display:flex;flex-direction:column;z-index:200;overflow:hidden;
  box-shadow:-2px 0 12px rgba(0,0,0,.08);
}
#detail-panel.open{transform:translateX(0);}
#dp-head{
  padding:14px 16px;border-bottom:1px solid var(--border);
  display:flex;align-items:flex-start;gap:10px;flex-shrink:0;background:#f6f8fa;
}
#dp-icon{font-size:22px;flex-shrink:0;margin-top:1px;}
#dp-title{font-size:13.5px;font-weight:700;color:var(--text);word-break:break-word;line-height:1.3;}
#dp-sub{font-size:10.5px;color:var(--muted);margin-top:3px;}
#dp-close{
  margin-left:auto;flex-shrink:0;width:26px;height:26px;border-radius:6px;
  border:1px solid var(--border);background:transparent;color:var(--muted);
  cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;
}
#dp-close:hover{background:var(--surf2);color:var(--text);}
#dp-body{flex:1;overflow-y:auto;padding:14px 16px;font-size:12.5px;}
#dp-body::-webkit-scrollbar{width:4px;}
#dp-body::-webkit-scrollbar-thumb{background:#d0d7de;border-radius:2px;}
.dr{margin-bottom:11px;}
.dl{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;
    letter-spacing:.6px;margin-bottom:4px;}
.dv{color:var(--text);line-height:1.5;word-break:break-word;}
.ddiv{border:none;border-top:1px solid var(--border);margin:12px 0;}
.stage-block{
  background:#f6f8fa;border:1px solid var(--border);border-radius:7px;
  padding:10px 12px;margin-bottom:8px;
}
.stage-block-title{font-size:11px;font-weight:700;color:var(--text);margin-bottom:6px;
  display:flex;align-items:center;gap:6px;}
.mc{padding:1px 8px;border-radius:10px;font-size:9px;font-weight:700;}
.mc-src{background:#dbeafe;color:#1d4ed8;}
.mc-tgt{background:#dcfce7;color:#166534;}
.mc-bulk{background:#fef3c7;color:#92400e;}
.mc-upd{background:#ecfdf5;color:#065f46;}
.mc-ups{background:#fffbeb;color:#92400e;}
.sql-box{
  background:#f6f8fa;border:1px solid #d0d7de;border-radius:5px;
  padding:8px 10px;font-family:'Cascadia Code','JetBrains Mono',monospace;
  font-size:10.5px;line-height:1.65;color:#24292f;
  overflow-x:auto;white-space:pre;max-height:220px;overflow-y:auto;margin-top:5px;
}
.kw{color:#0550ae;font-weight:600;}
.str{color:#0a3069;}
.num{color:#953800;}
.cmt{color:#6e7781;font-style:italic;}
.pr{display:flex;gap:8px;margin:2px 0;font-size:11.5px;}
.pk{color:var(--muted);width:120px;flex-shrink:0;}
.pv{color:var(--text);}
.lo{
  display:flex;align-items:center;gap:7px;padding:5px 8px;
  border-radius:6px;background:#f6f8fa;border:1px solid #e8ecf0;
  font-size:11px;margin:3px 0;
}
.lo-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0;}
#legend{
  position:fixed;bottom:44px;left:14px;
  background:rgba(255,255,255,.95);backdrop-filter:blur(6px);
  border:1px solid var(--border);border-radius:8px;
  padding:8px 12px;font-size:10.5px;z-index:100;
  box-shadow:0 2px 8px rgba(0,0,0,.08);
}
.lr{display:flex;align-items:center;gap:8px;margin:3px 0;color:var(--muted);}
.ll{width:26px;height:2px;border-radius:1px;}
#infobar{
  position:fixed;bottom:12px;left:50%;transform:translateX(-50%);
  background:rgba(255,255,255,.9);backdrop-filter:blur(6px);
  border:1px solid var(--border);border-radius:20px;
  padding:5px 16px;font-size:10.5px;color:var(--muted);
  pointer-events:none;z-index:100;white-space:nowrap;
  box-shadow:0 1px 4px rgba(0,0,0,.1);
}
::-webkit-scrollbar{width:5px;height:5px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:#d0d7de;border-radius:3px;}
"""

    js = r"""
const SEQS = /** SEQS_JSON **/;

const $=id=>document.getElementById(id);
const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function sqlHL(s){
  if(!s)return'';
  return esc(s)
    .replace(/\b(SELECT|FROM|WHERE|AND|OR|NOT|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|GROUP\s+BY|ORDER\s+BY|HAVING|UNION|ALL|INSERT|UPDATE|DELETE|INTO|VALUES|SET|TRUNCATE|AS|DISTINCT|COUNT|SUM|MAX|MIN|AVG|CASE|WHEN|THEN|ELSE|END|NULL|IS|IN|EXISTS|BETWEEN|LIKE|WITH|BY|ASC|DESC|ROWNUM|MINUS)\b/gi,
      m=>`<span class="kw">${m}</span>`)
    .replace(/'[^']*'/g,m=>`<span class="str">${m}</span>`)
    .replace(/\b(\d+)\b/g,m=>`<span class="num">${m}</span>`)
    .replace(/--.*/g,m=>`<span class="cmt">${m}</span>`);
}

const ICONS={job:'▶',sync:'⊕',stop:'🛑',condition:'◈',vars:'📋',
             routine:'🔧',exec:'💻',loop_start:'↩',loop_end:'↪',
             exception:'⚠',other:'◻'};
const COND_COL={'2':'#1a7f37','4':'#cf222e','0':'#8c959f','':'#0969da','6':'#9a6700','1':'#6e40c9'};
const COND_LBL={'2':'OK','4':'NOK','0':'','':'','6':'conditie','1':'conditie'};

let tx={x:80,y:80},sc=0.9,panning=false,ps={x:0,y:0};
let currentSeq=null,selectedNode=null;
const wrap=document.getElementById('canvas-wrap');
const canvas=document.getElementById('canvas');

function applyT(){
  canvas.style.transform=`translate(${tx.x}px,${tx.y}px) scale(${sc})`;
}

// ── Tabs
function buildTabs(){
  const bar=$('seq-tabs');
  SEQS.forEach((s,i)=>{
    const btn=document.createElement('button');
    btn.className='stab'+(i===0?' active':'');
    btn.textContent=s.id;
    btn.onclick=()=>{
      document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      closeDetail();
      currentSeq=s;
      renderFlow(s);
    };
    bar.appendChild(btn);
  });
}

// ── Layout: Sugiyama-stijl kolommen op basis van topo_rank
function computeLayout(seq){
  const NW=170,NH=88,XGAP=90,YGAP=20;
  const rank=seq.topo_rank;

  const byRank={};
  seq.nodes.forEach(n=>{
    const r=rank[n.id]||0;
    if(!byRank[r])byRank[r]=[];
    byRank[r].push(n);
  });

  const rankX={};
  Object.keys(byRank).map(Number).sort((a,b)=>a-b).forEach((r,i)=>{
    rankX[r]=i*(NW+XGAP);
  });

  const ORDER={job:0,loop_start:1,loop_end:1,condition:2,sync:3,
               vars:4,routine:4,exec:4,exception:4,stop:5,other:6};
  const positions={};
  Object.entries(byRank).forEach(([r,grp])=>{
    grp.sort((a,b)=>(ORDER[a.kind]||5)-(ORDER[b.kind]||5));
    grp.forEach((n,i)=>{
      positions[n.id]={x:rankX[parseInt(r)],y:i*(NH+YGAP),w:NW,h:NH};
    });
  });

  const maxX=Math.max(...Object.values(positions).map(p=>p.x+p.w))+80;
  const maxY=Math.max(...Object.values(positions).map(p=>p.y+p.h))+80;
  return{positions,canvasW:maxX,canvasH:maxY,NW,NH};
}

// ── Render
function renderFlow(seq){
  canvas.innerHTML='<svg id="svgl" style="position:absolute;top:0;left:0;pointer-events:none;"></svg>';
  const svgEl=canvas.querySelector('#svgl');
  const{positions,canvasW,canvasH,NW,NH}=computeLayout(seq);

  canvas.style.width=canvasW+'px';
  canvas.style.height=canvasH+'px';
  svgEl.setAttribute('width',canvasW);
  svgEl.setAttribute('height',canvasH);
  svgEl.style.cssText=`position:absolute;top:0;left:0;width:${canvasW}px;height:${canvasH}px;pointer-events:none;`;

  seq.nodes.forEach(n=>{
    const pos=positions[n.id];
    if(!pos)return;
    const hasD=n.kind==='job'&&n.par_stages&&n.par_stages.length>0;
    let badge='';
    if(n.kind==='job')
      badge=`<span class="node-badge badge-job">${esc(n.jobname||n.name)}</span>`;
    else if(n.kind==='sync')
      badge=`<span class="node-badge badge-${n.gate==='AND'?'and':'or'}">${n.gate||'?'}-gate</span>`;
    else if(n.kind==='stop')
      badge='<span class="node-badge badge-stop">STOP</span>';

    const SUB={job:'job-activiteit',sync:'synchronisatie',stop:'afbreken',
               condition:'conditie',vars:'variabelen',routine:'routine',
               exec:'commando',loop_start:'loop start',loop_end:'loop einde',
               exception:'exception'};

    const div=document.createElement('div');
    div.className=`node kind-${n.kind}${hasD?' has-details':''}`;
    div.id='nd-'+n.id;
    div.style.cssText=`left:${pos.x}px;top:${pos.y}px;width:${pos.w}px;`;
    div.innerHTML=`<div class="node-icon">${ICONS[n.kind]||'◻'}</div>
      <div class="node-name">${esc(n.name)}</div>
      <div class="node-sub">${SUB[n.kind]||''}</div>
      ${badge}`;
    div.addEventListener('click',()=>selectNode(n.id,seq));
    canvas.appendChild(div);
  });

  setTimeout(()=>drawLinks(seq.links,positions,NW,NH,svgEl),40);
  setTimeout(()=>fit(),80);
}

function drawLinks(links,pos,NW,NH,svgEl){
  svgEl.innerHTML=`<defs>
    <marker id="m-ok"  markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
      <polygon points="0 0,9 3.5,0 7" fill="#1a7f37" opacity=".9"/></marker>
    <marker id="m-nok" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
      <polygon points="0 0,9 3.5,0 7" fill="#cf222e" opacity=".9"/></marker>
    <marker id="m-und" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
      <polygon points="0 0,9 3.5,0 7" fill="#8c959f" opacity=".8"/></marker>
    <marker id="m-cnd" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
      <polygon points="0 0,9 3.5,0 7" fill="#9a6700" opacity=".85"/></marker>
  </defs>`;

  links.forEach(lnk=>{
    const fp=pos[lnk.from],tp=pos[lnk.to];
    if(!fp||!tp)return;
    const x1=fp.x+NW,y1=fp.y+NH/2;
    const x2=tp.x,   y2=tp.y+NH/2;
    const cx=(x1+x2)/2;
    const col=COND_COL[lnk.cond]||'#64748b';
    const mid=lnk.cond==='2'?'m-ok':lnk.cond==='4'?'m-nok':
              lnk.cond==='6'||lnk.cond==='1'?'m-cnd':'m-und';
    const dash=(lnk.cond===''||lnk.cond==='0')?' stroke-dasharray="6,4"':'';

    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',`M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`);
    path.setAttribute('fill','none');
    path.setAttribute('stroke',col);
    path.setAttribute('stroke-width','1.8');
    path.setAttribute('opacity','0.7');
    path.setAttribute('marker-end',`url(#${mid})`);
    if(dash)path.setAttribute('stroke-dasharray','6,4');
    svgEl.appendChild(path);

    const lbl=COND_LBL[lnk.cond];
    if(lbl){
      const mx=(x1+x2)/2,my=(y1+y2)/2-2;
      const bg=document.createElementNS('http://www.w3.org/2000/svg','rect');
      bg.setAttribute('x',mx-14);bg.setAttribute('y',my-9);
      bg.setAttribute('width',28);bg.setAttribute('height',13);
      bg.setAttribute('rx',4);bg.setAttribute('fill','#ffffff');bg.setAttribute('opacity','.92');
      svgEl.appendChild(bg);
      const txt=document.createElementNS('http://www.w3.org/2000/svg','text');
      txt.setAttribute('x',mx);txt.setAttribute('y',my);
      txt.setAttribute('text-anchor','middle');txt.setAttribute('dominant-baseline','middle');
      txt.setAttribute('font-size','9');txt.setAttribute('font-weight','700');
      txt.setAttribute('fill',col);txt.setAttribute('opacity','.95');
      txt.textContent=lbl;
      svgEl.appendChild(txt);
    }
  });
}

// ── Selectie & detail
function selectNode(nid,seq){
  if(selectedNode){
    const prev=document.getElementById('nd-'+selectedNode);
    if(prev)prev.classList.remove('selected');
  }
  selectedNode=nid;
  const el=document.getElementById('nd-'+nid);
  if(el)el.classList.add('selected');
  const node=seq.nodes.find(n=>n.id===nid);
  if(node)showDetail(node,seq);
}

function showDetail(node,seq){
  $('dp-icon').textContent=ICONS[node.kind]||'◻';
  $('dp-title').textContent=node.name;
  $('dp-sub').textContent=node.jobname||node.kind;

  let html='';

  const outL=seq.links.filter(l=>l.from===node.id);
  const inL =seq.links.filter(l=>l.to===node.id);

  if(outL.length){
    html+=`<div class="dr"><div class="dl">Gaat naar</div>`;
    outL.forEach(l=>{
      const tgt=seq.nodes.find(n=>n.id===l.to);
      const col=COND_COL[l.cond]||'#64748b';
      const lbl=COND_LBL[l.cond]||'';
      html+=`<div class="lo">
        <div class="lo-dot" style="background:${col}"></div>
        <span style="flex:1">${esc(tgt?tgt.name:l.to)}</span>
        ${lbl?`<span style="font-size:9px;font-weight:700;color:${col}">${esc(lbl)}</span>`:''}
      </div>`;
    });
    html+='</div>';
  }
  if(inL.length){
    html+=`<div class="dr"><div class="dl">Komt van</div>`;
    inL.forEach(l=>{
      const src=seq.nodes.find(n=>n.id===l.from);
      const col=COND_COL[l.cond]||'#64748b';
      html+=`<div class="lo">
        <div class="lo-dot" style="background:${col};opacity:.45"></div>
        <span style="color:var(--muted)">← ${esc(src?src.name:l.from)}</span>
      </div>`;
    });
    html+='</div>';
  }

  if(node.kind==='sync'){
    html+=`<hr class="ddiv"><div class="dr">
      <div class="dl">Gate type</div>
      <div class="dv">${node.gate==='AND'
        ?'⊕ AND — wacht tot <em>alle</em> inkomende paden klaar zijn'
        :'⊙ OR — gaat door zodra <em>één</em> inkomend pad klaar is'}</div>
    </div>`;
  }

  if(node.kind==='job'&&node.par_stages&&node.par_stages.length){
    html+='<hr class="ddiv">';
    node.par_stages.forEach(s=>{
      const wm=s.writemode||'';
      const mc=s.mode==='SOURCE'?'mc-src':
               wm==='BULK LOAD'?'mc-bulk':wm==='UPDATE'?'mc-upd':
               wm==='UPSERT/MERGE'?'mc-ups':'mc-tgt';
      const lbl=s.mode==='SOURCE'?'SOURCE':(wm||'INSERT');
      html+=`<div class="stage-block">
        <div class="stage-block-title">
          <span class="mc ${mc}">${esc(lbl)}</span>
          <span>${esc(s.name)}</span>
        </div>`;
      if(s.table)html+=`<div class="pr"><span class="pk">Tabel</span>
        <span class="pv" style="font-family:monospace;color:var(--accent2)">${esc(s.table)}</span></div>`;
      if(s.array)html+=`<div class="pr"><span class="pk">ArraySize</span><span class="pv">${esc(s.array)}</span></div>`;
      if(s.gen_sql)html+=`<div class="pr"><span class="pk">GenerateSQL</span>
        <span class="pv">${s.gen_sql==='1'?'✓ ja':'✗ nee'}</span></div>`;
      if(s.before_sql)html+=`<div class="dl" style="margin-top:8px">BeforeSQL</div>
        <div class="sql-box">${sqlHL(s.before_sql)}</div>`;
      if(s.after_sql)html+=`<div class="dl" style="margin-top:8px">AfterSQL</div>
        <div class="sql-box">${sqlHL(s.after_sql)}</div>`;
      if(s.where)html+=`<div class="dl" style="margin-top:8px">WHERE clause</div>
        <div class="sql-box">${sqlHL(s.where)}</div>`;
      if(s.sql)html+=`<div class="dl" style="margin-top:8px">SQL</div>
        <div class="sql-box">${sqlHL(s.sql)}</div>`;
      html+='</div>';
    });
  } else if(node.kind==='job'&&node.jobname){
    html+=`<hr class="ddiv"><div class="dr">
      <div class="dl">Aanroept</div>
      <div class="dv" style="color:var(--muted);font-size:11.5px">${esc(node.jobname)}<br>
        <em>(externe job)</em></div></div>`;
  }

  $('dp-body').innerHTML=html;
  $('detail-panel').classList.add('open');
}

function closeDetail(){
  $('detail-panel').classList.remove('open');
  if(selectedNode){
    const el=document.getElementById('nd-'+selectedNode);
    if(el)el.classList.remove('selected');
    selectedNode=null;
  }
}

// ── Pan & zoom
wrap.addEventListener('wheel',e=>{
  e.preventDefault();
  const f=e.deltaY<0?1.12:1/1.12;
  const r=wrap.getBoundingClientRect();
  const mx=e.clientX-r.left,my=e.clientY-r.top;
  const ox=tx.x,oy=tx.y;
  tx.x=mx-(mx-ox)*f; tx.y=my-(my-oy)*f;
  sc=Math.max(.08,Math.min(3,sc*f));
  applyT();
},{passive:false});

wrap.addEventListener('mousedown',e=>{
  if(e.target.closest('.node'))return;
  panning=true;ps={x:e.clientX-tx.x,y:e.clientY-tx.y};
  wrap.style.cursor='grabbing';
});
window.addEventListener('mousemove',e=>{
  if(!panning)return;
  tx={x:e.clientX-ps.x,y:e.clientY-ps.y};
  applyT();
});
window.addEventListener('mouseup',()=>{panning=false;wrap.style.cursor='';});

function fit(){
  const ww=wrap.clientWidth,wh=wrap.clientHeight;
  const cw=parseFloat(canvas.style.width||800);
  const ch=parseFloat(canvas.style.height||600);
  sc=Math.min((ww-100)/cw,(wh-100)/ch,1.4);
  tx={x:(ww-cw*sc)/2,y:(wh-ch*sc)/2};
  applyT();
}
function resetZoom(){sc=1;tx={x:80,y:80};applyT();}

buildTabs();
if(SEQS.length){currentSeq=SEQS[0];renderFlow(SEQS[0]);}
"""

    js = js.replace('/** SEQS_JSON **/', seqs_json)

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<title>{title_esc} — Sequencer Flow</title>
<style>{css}</style>
</head>
<body>
<div id="toolbar">
  <div id="uwv-logo">UWV</div>
  <div id="toolbar-title"><strong>{title_esc}</strong> — Sequencer Flow <span style="font-size:11px">(export {htmllib.escape(export_date)})</span></div>
  <div id="seq-tabs"></div>
  <div id="toolbar-right">
    <button class="tbtn" onclick="fit()">⊡ Fit</button>
    <button class="tbtn" onclick="resetZoom()">1:1</button>
  </div>
</div>
<div id="canvas-wrap">
  <div id="canvas">
    <svg id="svgl" style="position:absolute;top:0;left:0;pointer-events:none;"></svg>
  </div>
</div>
<div id="detail-panel">
  <div id="dp-head">
    <div id="dp-icon">▶</div>
    <div style="flex:1">
      <div id="dp-title">—</div>
      <div id="dp-sub"></div>
    </div>
    <button id="dp-close" onclick="closeDetail()">✕</button>
  </div>
  <div id="dp-body"></div>
</div>
<div id="legend">
  <div class="lr"><div class="ll" style="background:#3fb950"></div>OK</div>
  <div class="lr"><div class="ll" style="background:#f85149"></div>NOK</div>
  <div class="lr"><div class="ll" style="background:#64748b;height:0;border-top:2px dashed #64748b"></div>onvoorwaardelijk</div>
</div>
<div id="infobar">Scroll = zoom · Sleep = pan · Klik node voor details</div>
<script>{js}</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info('=' * 60)
    log.info('DataStage XML → Sequencer Flow gestart')

    xml_path = ds.find_xml_file()
    content  = ds.read_xml(xml_path)
    ds.validate_dse(content, xml_path)

    hm          = re.search(r'<Header[^>]+Date="([^"]+)"', content)
    export_date = hm.group(1) if hm else '?'
    log.info('Export datum: %s', export_date)

    log.info('Sequencers/jobs parsen...')
    seqs = parse_all(content)

    for s in seqs:
        log.info('  %-50s  %d nodes  %d links',
                 s['id'], len(s['nodes']), len(s['links']))

    title       = xml_path.stem.replace('_', ' ').title()
    html_out    = build_html(seqs, title, export_date)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f'{xml_path.stem}_Flow.html'
    output_path.write_text(html_out, encoding='utf-8')

    log.info('─' * 60)
    log.info('Flow diagram klaar: %s', output_path.name)
    log.info('  Sequencers      : %d', len(seqs))
    log.info('  Bestandsgrootte : %d bytes', output_path.stat().st_size)
    log.info('─' * 60)


if __name__ == '__main__':
    main()
