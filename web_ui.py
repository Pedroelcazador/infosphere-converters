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
import zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote

ROOT_DIR   = Path(__file__).resolve().parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
PORT       = 8080
MAX_UPLOAD = 50 * 1024 * 1024  # 50 MB

sys.path.insert(0, str(ROOT_DIR))

# ---------------------------------------------------------------------------
# Converter-registry — afgeleid uit converters.py
# ---------------------------------------------------------------------------
from converters import REGISTRY as _REGISTRY

CONVERTERS = {c['name']: c['script'] for c in _REGISTRY if c['script']}

AUTO_RUN: dict[str, list[str]] = {}
for _c in _REGISTRY:
    AUTO_RUN.setdefault(_c['file_type'], []).append(_c['name'])

TAB_LABELS         = {c['name']: c['tab_label']     for c in _REGISTRY}
CONV_OUTPUT_SUFFIX = {c['name']: c['output_suffix'] for c in _REGISTRY}


# ---------------------------------------------------------------------------
# Bestandstype detectie
# ---------------------------------------------------------------------------
def _dsexport_has_sequence(content: bytes) -> bool:
    """Geeft True als de DSExport minstens één sequencer-job bevat."""
    from xml.etree import ElementTree as ET
    try:
        root = ET.fromstring(content.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return False
    for job in root.findall("Job"):
        if job.get("Type") == "2":
            return True
        if any(rec.get("Type") == "JSJobActivity" for rec in job.findall("Record")):
            return True
    return False


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
    existing = [f for f in INPUT_DIR.iterdir() if f.is_file()]
    if existing:
        names = ", ".join(f.name for f in existing)
        return {"type": "unknown", "tabs": [], "log": "",
                "error": f"Er staat al een bestand in de inputmap ({names}). "
                         f"Gebruik 'Nieuwe sessie' om de map leeg te maken voor een nieuwe conversie."}
    for f2 in OUTPUT_DIR.iterdir():
        if f2.is_file():
            f2.unlink()
    (INPUT_DIR / filename).write_bytes(file_content)
    ftype = detect_type(file_content, filename)
    if ftype == "unknown":
        return {"type":"unknown","tabs":[],"log":"Onbekend: "+filename,"error":"Bestandstype niet herkend."}
    to_run = list(AUTO_RUN[ftype])
    if ftype == "dsexport":
        if _dsexport_has_sequence(file_content):
            to_run = [c for c in to_run if c != "ds_job_flow"]
        else:
            to_run = [c for c in to_run if c != "ds_flow"]
    log_lines = ["Bestand: "+filename, "Type: "+ftype, ""]
    errors = []
    for conv_name in to_run:
        sp = CONVERTERS.get(conv_name)
        if not sp:
            continue  # tab-only entry (geen eigen converter)
        if not sp.exists():
            log_lines.append("  ? Niet gevonden: "+conv_name); continue
        log_lines.append(">> "+conv_name)
        for h in logging.root.handlers[:]: logging.root.removeHandler(h)
        lb = LogCapture()
        sh = logging.StreamHandler(lb)
        sh.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        logging.root.addHandler(sh); logging.root.setLevel(logging.INFO)
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
        elif path == "/readme":
            readme = ROOT_DIR / "README.md"
            if not readme.exists():
                self._send(404, "text/plain", b"README.md niet gevonden")
                return
            from md_to_html import md_to_html
            html = md_to_html(readme.read_text(encoding="utf-8"),
                              title="Infosphere Converters — Documentatie")
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
        elif path == "/download-zip":
            files = [f for f in OUTPUT_DIR.iterdir() if f.is_file()]
            if not files:
                self._send(404, "text/plain", b"Geen outputbestanden beschikbaar")
                return
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, f.name)
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="output.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/output/"):
            fname = unquote(path[8:])
            fpath = (OUTPUT_DIR / fname).resolve()
            if not fpath.is_relative_to(OUTPUT_DIR.resolve()):
                self._send(404, "text/plain", b"Niet gevonden")
                return
            if fpath.exists() and fpath.is_file():
                ct = mimetypes.guess_type(fname)[0] or "application/octet-stream"
                self._send(200, ct, fpath.read_bytes())
            else:
                self._send(404, "text/plain", b"Niet gevonden")
        else:
            self._send(404, "text/plain", b"Niet gevonden")

    def do_POST(self):
        if self.path == "/reset":
            for f in list(INPUT_DIR.iterdir()):
                if f.is_file(): f.unlink()
            self._json({"ok": True})
            return
        if self.path != "/convert":
            self._send(404, "text/plain", b"Niet gevonden")
            return
        ct  = self.headers.get("Content-Type", "")
        cl  = int(self.headers.get("Content-Length", 0))
        if cl > MAX_UPLOAD:
            self._json({"error": f"Bestand te groot (max {MAX_UPLOAD // (1024*1024)} MB).", "tabs": [], "log": ""})
            return
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
UI_HTML = (ROOT_DIR / 'web_ui_template.html').read_text(encoding='utf-8')


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
    def _open_browser(url):
        if sys.platform == "win32":
            import subprocess
            subprocess.Popen(["cmd", "/c", "start", "msedge", url])
        else:
            webbrowser.open(url)
    threading.Timer(0.8, lambda: _open_browser(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  Server gestopt.")
        server.server_close()


if __name__ == "__main__":
    start()
