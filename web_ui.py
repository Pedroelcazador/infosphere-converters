#!/usr/bin/env python3
# Versie: 2026-03-03 16:00
"""
Infosphere Converters - Web UI

Gebruik:
  python3 main.py --web
  (of direct: python3 web_ui.py)

Start een lokale webserver op http://localhost:8080.
De browser wordt automatisch geopend.
"""

import sys
import io
import json
import mimetypes
import threading
import webbrowser
import traceback
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote

ROOT_DIR   = Path(__file__).resolve().parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
PORT       = 8080

sys.path.insert(0, str(ROOT_DIR))

# ---------------------------------------------------------------------------
# Converter-registry
# ---------------------------------------------------------------------------
CONVERTERS = {
    'ds_convert':  ROOT_DIR / 'ds_convert'  / 'ds_convert.py',
    'ds_flow':     ROOT_DIR / 'ds_flow'     / 'ds_flow.py',
    'ds_job_flow': ROOT_DIR / 'ds_job_flow' / 'ds_job_flow.py',
    'ldm_convert': ROOT_DIR / 'ldm_convert' / 'ldm_convert.py',
    'msl_convert': ROOT_DIR / 'msl_convert' / 'msl_convert.py',
    'msl_lineage': ROOT_DIR / 'msl_lineage' / 'msl_lineage.py',
}

AUTO_RUN = {
    'dsexport': ['ds_convert', 'ds_flow', 'ds_job_flow'],
    'ldm':      ['ldm_convert'],
    'msl':      ['msl_convert', 'msl_lineage'],
}

TAB_LABELS = {
    'ds_convert':  'Documentatie',
    'ds_flow':     'Flow',
    'ds_job_flow': 'Job Flow',
    'ldm_convert': 'Documentatie',
    'msl_convert': 'Mapping',
    'msl_lineage': 'Lineage',
}

CONV_OUTPUT_SUFFIX = {
    'ds_convert':  '_DataStage.html',
    'ds_flow':     '_Flow.html',
    'ds_job_flow': '_JobFlow.html',
    'ldm_convert': '_ERD.html',
    'msl_convert': '_Mapping.html',
    'msl_lineage': '_Lineage.html',
}


# ---------------------------------------------------------------------------
# Bestandstype detectie
# ---------------------------------------------------------------------------
def detect_type(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".msl"):
        return "msl"
    try:
        text = content[:4096].decode("utf-8", errors="replace")
    except Exception:
        return "unknown"
    if "<DSExport" in text:
        return "dsexport"
    if "logicalModelElement" in text:
        return "ldm"
    return "unknown"


class LogCapture(io.StringIO):
    def write(self, s):
        sys.__stdout__.write(s)
        return super().write(s)

def run_conversion(file_content, filename):
    import logging, importlib.util
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    [f2.unlink() for f2 in list(INPUT_DIR.iterdir()) if f2.is_file()]
    [f2.unlink() for f2 in list(OUTPUT_DIR.iterdir()) if f2.is_file()]
    (INPUT_DIR / filename).write_bytes(file_content)
    ftype = detect_type(file_content, filename)
    if ftype == "unknown":
        return {"type":"unknown","tabs":[],"log":"Onbekend: "+filename,"error":"Bestandstype niet herkend."}
    to_run = AUTO_RUN[ftype]
    log_lines = ["Bestand: "+filename, "Type: "+ftype, ""]
    errors = []
    for conv_name in to_run:
        sp = CONVERTERS.get(conv_name)
        if not sp or not sp.exists():
            log_lines.append("  ? Niet gevonden: "+conv_name); continue
        log_lines.append(">> "+conv_name)
        for h in logging.root.handlers[:]: logging.root.removeHandler(h)
        lb = LogCapture()
        sh = logging.StreamHandler(lb)
        sh.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        logging.root.addHandler(sh); logging.root.setLevel(logging.INFO)
        old=sys.argv[:]; sys.argv=[str(sp)]
        try:
            spec=importlib.util.spec_from_file_location(conv_name,sp)
            mod=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod); mod.main()
            log_lines.append("   OK")
        except SystemExit as e:
            if e.code not in (0,None): errors.append(conv_name+": exit "+str(e.code)); log_lines.append("   FOUT exit "+str(e.code))
            else: log_lines.append("   OK")
        except Exception:
            tb=traceback.format_exc(); errors.append(conv_name+": "+tb); log_lines.append("   FOUT: "+tb)
        finally:
            sys.argv=old
            for h in logging.root.handlers[:]: logging.root.removeHandler(h)
        cap=lb.getvalue().strip()
        if cap: log_lines.append(cap)
        log_lines.append("")

    ofiles = {f2.name: f2 for f2 in OUTPUT_DIR.iterdir() if f2.is_file() and f2.suffix == ".html"}
    tabs = []
    for cn in to_run:
        suf = CONV_OUTPUT_SUFFIX.get(cn, "")
        m = next((k for k in ofiles if k.endswith(suf)), None)
        if m:
            tabs.append({"label": TAB_LABELS.get(cn, cn), "filename": m, "conv": cn})
    log_str = "\n".join(str(l) for l in log_lines)
    err_str = "\n".join(errors) if errors else None
    return {"type": ftype, "tabs": tabs, "log": log_str, "error": err_str}


# ---------------------------------------------------------------------------
# Multipart parser (stdlib only)
# ---------------------------------------------------------------------------
def parse_multipart(content_type: str, body: bytes):
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip().strip('"')
    if not boundary:
        raise ValueError("Geen boundary in Content-Type")
    sep   = ("--" + boundary).encode()
    end   = ("--" + boundary + "--").encode()
    parts = body.split(sep)
    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--" or part.startswith(b"--"):
            continue
        if end in part:
            part = part[: part.index(end)].strip(b"\r\n")
        if b"\r\n\r\n" in part:
            hdr_raw, content = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            hdr_raw, content = part.split(b"\n\n", 1)
        else:
            continue
        hdr_str = hdr_raw.decode("utf-8", errors="replace")
        filename = None
        for line in hdr_str.splitlines():
            if "Content-Disposition" in line and "filename=" in line:
                for seg in line.split(";"):
                    seg = seg.strip()
                    if seg.startswith("filename="):
                        filename = seg[9:].strip().strip('"')
        if filename:
            return filename, content.rstrip(b"\r\n")
    raise ValueError("Geen bestand in upload")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # stil

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", UI_HTML.encode("utf-8"))
        elif path.startswith("/output/"):
            fname = unquote(path[8:])
            fpath = OUTPUT_DIR / fname
            if fpath.exists() and fpath.is_file():
                ct = mimetypes.guess_type(fname)[0] or "application/octet-stream"
                self._send(200, ct, fpath.read_bytes())
            else:
                self._send(404, "text/plain", b"Niet gevonden")
        else:
            self._send(404, "text/plain", b"Niet gevonden")

    def do_POST(self):
        if self.path != "/convert":
            self._send(404, "text/plain", b"Niet gevonden")
            return
        ct  = self.headers.get("Content-Type", "")
        cl  = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(cl)
        try:
            filename, content = parse_multipart(ct, body)
        except Exception as e:
            self._json({"error": f"Upload mislukt: {e}", "tabs": [], "log": ""})
            return
        try:
            result = run_conversion(content, filename)
        except Exception:
            tb = traceback.format_exc()
            result = {"error": tb, "tabs": [], "log": tb}
        self._json(result)

    def _send(self, code, ct, data):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", data)


# ---------------------------------------------------------------------------
# UI HTML
# ---------------------------------------------------------------------------
UI_HTML = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<title>Infosphere Converters</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#eef2f7;color:#1a2a3a;height:100vh;display:flex;flex-direction:column;overflow:hidden}
#hdr{background:#005b9a;padding:0 20px;height:52px;display:flex;align-items:center;gap:14px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,.2)}
#logo{font-size:17px;font-weight:700;background:#fff;color:#005b9a;padding:2px 9px;border-radius:3px}
#hdr h1{font-size:14px;font-weight:400;color:#cce0f5}
#hdr h1 strong{color:#fff;font-weight:700}
#hdr-status{margin-left:auto;font-size:11px;color:rgba(255,255,255,.6)}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden;padding:16px;gap:12px}
#drop-area{border:2.5px dashed #a0b8d0;border-radius:8px;background:#fff;text-align:center;padding:28px 20px;cursor:pointer;transition:border-color .2s,background .2s;flex-shrink:0;position:relative}
#drop-area.dragover{border-color:#005b9a;background:#e8f2fb}
#drop-area.loading{border-color:#005b9a;background:#f0f7ff;cursor:wait}
#drop-icon{font-size:36px;line-height:1;margin-bottom:8px}
#drop-text{font-size:14px;color:#4a6a8a}
#drop-text strong{color:#005b9a}
#drop-sub{font-size:11px;color:#8899aa;margin-top:5px}
#file-input{display:none}
#spinner{display:none;position:absolute;inset:0;background:rgba(240,247,255,.9);border-radius:6px;align-items:center;justify-content:center;flex-direction:column;gap:10px;font-size:13px;color:#005b9a}
#drop-area.loading #spinner{display:flex}
.spin{width:32px;height:32px;border:3px solid #c0d8f0;border-top-color:#005b9a;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#err-bar{display:none;background:#fef0f0;border:1px solid #f0b0b0;border-radius:6px;padding:10px 14px;font-size:12px;color:#c03030;flex-shrink:0}
#out-section{flex:1;display:flex;flex-direction:column;background:#fff;border-radius:8px;border:1px solid #c8d8e8;overflow:hidden;min-height:0}
#out-section.hidden{display:none}
#tab-bar{display:flex;align-items:stretch;background:#f0f7ff;border-bottom:1px solid #c8d8e8;padding:0 12px;gap:2px;flex-shrink:0}
.tab{padding:9px 16px;font-size:12px;font-weight:600;color:#4a6a8a;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-1px;white-space:nowrap;transition:color .15s}
.tab:hover{color:#005b9a}
.tab.active{color:#005b9a;border-bottom-color:#005b9a}
#tab-actions{margin-left:auto;display:flex;align-items:center;gap:8px}
.abtn{padding:5px 12px;border-radius:4px;border:1.5px solid #005b9a;background:#fff;color:#005b9a;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap}
.abtn:hover{background:#e8f2fb}
.abtn.primary{background:#005b9a;color:#fff}
.abtn.primary:hover{background:#004a80}
#frame-wrap{flex:1;position:relative;min-height:0}
#frame{width:100%;height:100%;border:none;display:block}
#welcome{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:#8899aa;font-size:13px;pointer-events:none}
#welcome-icon{font-size:40px}
#log-sec{flex-shrink:0;background:#1c2c3c;border-radius:8px;overflow:hidden;max-height:140px;display:flex;flex-direction:column}
#log-sec.hidden{display:none}
#log-hdr{display:flex;align-items:center;padding:5px 12px;background:#142030;cursor:pointer;user-select:none;gap:8px}
#log-hdr span{font-size:11px;color:#6a9ac0;font-weight:600}
#log-tog{font-size:10px;color:#4a7a9a;margin-left:auto}
#log-body{flex:1;overflow-y:auto;padding:8px 12px;font-family:'Courier New',monospace;font-size:10px;color:#a8c8e8;line-height:1.5;white-space:pre-wrap;word-break:break-all}
.err{color:#f08080}
.ok{color:#80e0a0}
#log-sec.collapsed #log-body{display:none}
#log-sec.collapsed{max-height:32px}
</style>
</head>
<body>
<div id="hdr">
  <div id="logo">UWV</div>
  <h1><strong>Infosphere Converters</strong> \u2014 Web Interface</h1>
  <span id="hdr-status">Klaar</span>
</div>
<div id="main">
  <div id="drop-area" onclick="document.getElementById('file-input').click()">
    <div id="drop-icon">\U0001f4c2</div>
    <div id="drop-text"><strong>Sleep een bestand hiernaartoe</strong> of klik om te kiezen</div>
    <div id="drop-sub">Ondersteund: DataStage DSExport XML \u00b7 IBM LDM XML \u00b7 MSL</div>
    <div id="spinner"><div class="spin"></div><span id="spin-txt">Converteren\u2026</span></div>
  </div>
  <input type="file" id="file-input" accept=".xml,.msl">
  <div id="err-bar"></div>
  <div id="out-section" class="hidden">
    <div id="tab-bar">
      <div id="tab-actions">
        <button class="abtn" onclick="openNew()">\u2197 Nieuw venster</button>
        <button class="abtn primary" onclick="dl()">\u2b07 Opslaan</button>
      </div>
    </div>
    <div id="frame-wrap">
      <iframe id="frame" sandbox="allow-scripts allow-same-origin"></iframe>
      <div id="welcome"><div id="welcome-icon">\U0001f4c4</div><span>Sleep een bestand om te beginnen</span></div>
    </div>
  </div>
  <div id="log-sec" class="hidden">
    <div id="log-hdr" onclick="toggleLog()">
      <span>\u25b8 Log</span><span id="log-tog">\u25b4 inklappen</span>
    </div>
    <div id="log-body"></div>
  </div>
</div>
<script>
let tabs=[],idx=0,logColl=false;
const drop=document.getElementById('drop-area');
drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('dragover')});
drop.addEventListener('dragleave',()=>drop.classList.remove('dragover'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragover');if(e.dataTransfer.files[0])handle(e.dataTransfer.files[0])});
document.getElementById('file-input').addEventListener('change',e=>{if(e.target.files[0])handle(e.target.files[0]);e.target.value=''});
async function handle(file){
  setStatus('Bezig: '+file.name+'\u2026');setErr(null);
  drop.classList.add('loading');
  document.getElementById('spin-txt').textContent='Converteren: '+file.name+'\u2026';
  const fd=new FormData();fd.append('file',file,file.name);
  try{
    const r=await fetch('/convert',{method:'POST',body:fd});
    const res=await r.json();
    showLog(res.log||'');
    if(res.error){setErr(res.error);setStatus('Fout')}
    else{renderTabs(res.tabs);setStatus('Klaar \u2014 '+file.name)}
  }catch(e){setErr('Netwerkfout: '+e.message);setStatus('Fout')}
  finally{drop.classList.remove('loading','dragover')}
}
function renderTabs(t){
  tabs=t;idx=0;
  document.querySelectorAll('.tab').forEach(x=>x.remove());
  const bar=document.getElementById('tab-bar');
  const actions=document.getElementById('tab-actions');
  if(!t.length){document.getElementById('out-section').classList.add('hidden');return}
  t.forEach((tab,i)=>{
    const el=document.createElement('div');
    el.className='tab'+(i===0?' active':'');
    el.textContent=tab.label;
    el.onclick=()=>sw(i);
    bar.insertBefore(el,actions);
  });
  document.getElementById('out-section').classList.remove('hidden');
  document.getElementById('welcome').style.display='none';
  load(0);
}
function sw(i){idx=i;document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',j===i));load(i)}
function load(i){const t=tabs[i];if(t)document.getElementById('frame').src='/output/'+encodeURIComponent(t.filename)}
function dl(){const t=tabs[idx];if(!t)return;const a=document.createElement('a');a.href='/output/'+encodeURIComponent(t.filename);a.download=t.filename;a.click()}
function openNew(){const t=tabs[idx];if(t)window.open('/output/'+encodeURIComponent(t.filename),'_blank')}
function showLog(txt){
  const sec=document.getElementById('log-sec'),body=document.getElementById('log-body');
  sec.classList.remove('hidden','collapsed');logColl=false;
  document.getElementById('log-tog').textContent='\u25b4 inklappen';
  body.innerHTML=txt.split('\\n').map(l=>{
    if(l.includes('FOUT')||l.toLowerCase().includes('error'))return '<span class="err">'+esc(l)+'</span>';
    if(l.includes('OK')||l.includes('Klaar'))return '<span class="ok">'+esc(l)+'</span>';
    return esc(l);
  }).join('\\n');
  body.scrollTop=body.scrollHeight;
}
function toggleLog(){logColl=!logColl;document.getElementById('log-sec').classList.toggle('collapsed',logColl);document.getElementById('log-tog').textContent=logColl?'\u25be uitklappen':'\u25b4 inklappen'}
function setStatus(m){document.getElementById('hdr-status').textContent=m}
function setErr(m){const b=document.getElementById('err-bar');b.textContent=m?'\u26a0 '+m:'';b.style.display=m?'block':'none'}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Server starten
# ---------------------------------------------------------------------------
def start(port: int = PORT):
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    server = HTTPServer(("localhost", port), Handler)
    url = f"http://localhost:{port}"
    print(f"\n  Infosphere Converters - Web UI")
    print(f"  {url}")
    print(f"  Ctrl+C om te stoppen\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  Server gestopt.")
        server.server_close()


if __name__ == "__main__":
    start()
