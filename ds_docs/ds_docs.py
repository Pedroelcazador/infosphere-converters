"""
ds_docs.py — DataStage DSExport XML → gesplitste Markdown-documentatie (ZIP)

Genereert één .md-bestand per job + een index.md, verpakt in een ZIP-bestand.
Bedoeld als kennisbase voor LLMs/chatbots met beperkt context-venster.

Output: output/{xml_stem}_docs.zip
        output/{xml_stem}_Docs.html  (landing page voor web_ui-tab)
"""

import importlib.util
import logging
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT_DIR   = Path(__file__).resolve().parent.parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'
LOG_FILE   = Path(__file__).resolve().parent / 'ds_docs.log'

log = logging.getLogger(__name__)

# ── ds_convert laden via importlib ────────────────────────────────────────────

def _load_ds_convert():
    script = ROOT_DIR / 'ds_convert' / 'ds_convert.py'
    spec   = importlib.util.spec_from_file_location('ds_convert', script)
    mod    = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _first_sentence(text: str) -> str:
    """Geeft de eerste zin van een beschrijving (tot eerste punt+spatie of newline)."""
    if not text:
        return '—'
    for sep in ('. ', '.\n', '\n'):
        idx = text.find(sep)
        if idx != -1:
            return text[:idx + 1].strip()
    return text.strip()


def _sequence_summary(dsc, job_id: str, job_elem) -> str:
    """Bouwt een genummerde opsomming van de uitvoeringsstappen van een sequencer."""
    records = dsc.get_records(job_elem)
    id_to_name = {
        rid: (dsc.prop(elem, 'Name') or rid)
        for rid, (_, elem) in records.items()
    }
    lines = []
    step = 1
    for rec_id, (rec_type, rec_elem) in records.items():
        if rec_type == 'JSJobActivity':
            rec_name = dsc.prop(rec_elem, 'Name') or rec_id
            jobname  = dsc.prop(rec_elem, 'Jobname') or rec_name
            lines.append(f"{step}. **{rec_name}** → roept aan: `{jobname}`")
            step += 1
    return '\n'.join(lines) if lines else '*Geen stappen gevonden.*'


# ── index.md opbouwen ─────────────────────────────────────────────────────────

def _build_index(dsc, xml_stem: str, export_date: str, ts: str,
                 sequencer_jobs, parallel_jobs, container_jobs) -> str:
    title = xml_stem.replace('_', ' ').title()
    lines = [
        f"# DataStage Documentatie — {title}\n",
        f"*Gegenereerd op {ts} uit XML-export d.d. {export_date}*\n",
        "## Bestanden in dit archief\n",
        "Elk bestand bevat de volledige documentatie van één job.\n",
    ]

    if sequencer_jobs:
        lines += [
            "### Sequencer-jobs\n",
            "| Bestand | Jobname | Beschrijving |",
            "|---------|---------|--------------|",
        ]
        for job_id, job_elem, dm, tm in sequencer_jobs:
            name, func_desc, _, _ = dsc.get_job_header(job_elem, job_id)
            short = _first_sentence(func_desc)
            lines.append(f"| {job_id}.md | {name} | {short} |")
        lines.append("")

    if parallel_jobs:
        lines += [
            "### Parallel jobs\n",
            "| Bestand | Jobname | Beschrijving |",
            "|---------|---------|--------------|",
        ]
        for job_id, job_elem, dm, tm in parallel_jobs:
            name, func_desc, _, _ = dsc.get_job_header(job_elem, job_id)
            short = _first_sentence(func_desc)
            lines.append(f"| {job_id}.md | {name} | {short} |")
        lines.append("")

    if container_jobs:
        lines += [
            "### Generieke containers\n",
            "| Bestand | Beschrijving |",
            "|---------|--------------|",
        ]
        for cname, date_mod, sc_elem in container_jobs:
            defn = sc_elem.find("Record[@Identifier='ROOT'][@Type='ContainerDefn']")
            raw  = (dsc.prop(defn, 'Description') or '') if defn is not None else ''
            short = _first_sentence(dsc.parse_description(raw)[0])
            lines.append(f"| {cname}.md | {short} |")
        lines.append("")

    if sequencer_jobs:
        lines.append("## Sequence-structuur\n")
        for job_id, job_elem, dm, tm in sequencer_jobs:
            name, _, _, _ = dsc.get_job_header(job_elem, job_id)
            lines.append(f"### {name} (`{job_id}.md`)\n")
            lines.append(_sequence_summary(dsc, job_id, job_elem))
            lines.append("")

    return '\n'.join(lines)


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
    log.info("=" * 60)
    log.info("DataStage XML → Docs ZIP gestart")

    dsc = _load_ds_convert()

    xml_path = dsc.find_xml_file()
    content  = dsc.read_xml(xml_path)

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        log.error("XML kan niet worden geparsed: %s", e)
        log.error("Conversie afgebroken voor: %s", xml_path.name)
        sys.exit(1)

    dsc.validate_dse(root, xml_path)

    header      = root.find('Header')
    export_date = header.get('Date', '?') if header is not None else root.get('Date', '?')
    jobs        = dsc.split_jobs(root)
    log.info("Jobs verwerken: %d totaal", len(jobs))

    parallel_jobs, sequencer_jobs = [], []
    for job_id, job_type, job_elem in jobs:
        dm = job_elem.get('DateModified', '?')
        tm = job_elem.get('TimeModified', '?')
        is_seq = job_type == '2' or any(
            rec.get('Type') == 'JSJobActivity'
            for rec in job_elem.findall('Record')
        )
        if is_seq:
            sequencer_jobs.append((job_id, job_elem, dm, tm))
        else:
            parallel_jobs.append((job_id, job_elem, dm, tm))

    container_jobs = dsc.split_containers(root)

    ts       = datetime.now().strftime('%d-%m-%Y %H:%M')
    zip_name = f"{xml_path.stem}_docs.zip"

    index_md = _build_index(
        dsc, xml_path.stem, export_date, ts,
        sequencer_jobs, parallel_jobs, container_jobs
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / zip_name

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('index.md', index_md)
        log.info("  index.md toegevoegd")

        for job_id, job_elem, dm, tm in sequencer_jobs:
            log.info("  Sequencer: %s", job_id)
            md = dsc.render_sequencer_job(job_id, job_elem, dm, tm)
            zf.writestr(f'{job_id}.md', md)

        for job_id, job_elem, dm, tm in parallel_jobs:
            log.info("  Parallel : %s", job_id)
            md = dsc.render_parallel_job(job_id, job_elem, dm, tm)
            zf.writestr(f'{job_id}.md', md)

        for cname, date_mod, sc_elem in container_jobs:
            log.info("  Container: %s", cname)
            md = dsc.render_container(cname, sc_elem, date_mod)
            zf.writestr(f'{cname}.md', md)

    # Landing page voor web_ui-tab (triggert automatisch ZIP-download)
    html_path = OUTPUT_DIR / f"{xml_path.stem}_Docs.html"
    html_path.write_text(
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<title>DataStage Docs</title></head><body>'
        f'<p>Download: <a href="/output/{zip_name}">{zip_name}</a></p>'
        f'<script>window.location="/output/{zip_name}";</script>'
        f'</body></html>',
        encoding='utf-8'
    )

    n_files = 1 + len(sequencer_jobs) + len(parallel_jobs) + len(container_jobs)
    log.info("─" * 60)
    log.info("Conversie geslaagd: %s", xml_path.name)
    log.info("  Sequencer jobs  : %d", len(sequencer_jobs))
    log.info("  Parallel jobs   : %d", len(parallel_jobs))
    log.info("  Containers      : %d", len(container_jobs))
    log.info("  Bestanden in ZIP: %d (incl. index.md)", n_files)
    log.info("  ZIP output      : %s (%d bytes)", zip_path.name, zip_path.stat().st_size)
    log.info("─" * 60)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)-8s %(message)s')
    _main()
