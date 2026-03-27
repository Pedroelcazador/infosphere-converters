"""
Bouwt een distribueerbare ZIP van infosphere-converters.

Gebruik:
    python build_zip.py

Uitvoer: infosphere-converters-<versie>.zip in de projectroot.
Bevat alleen de bestanden die eindgebruikers nodig hebben.
"""

import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Bestanden in de root die meegenomen worden
ROOT_FILES = [
    "web_ui.py",
    "web_ui_template.html",
    "main.py",
    "md_to_html.py",
    "converters.py",
    "version.py",
    "start.bat",
    "start.sh",
]

# Converter-mappen: alleen .py en .html bestanden
CONVERTER_DIRS = [
    "ds_convert",
    "ds_flow",
    "ds_job_flow",
    "ldm_convert",
    "dbm_convert",
    "msl_convert",
    "msl_lineage",
]

ZIP_ROOT = "infosphere-converters"


def _add_empty_dir(zf: zipfile.ZipFile, path: str) -> None:
    info = zipfile.ZipInfo(path + "/")
    info.external_attr = 0o40755 << 16
    zf.writestr(info, "")


def build(output_path: Path, version: str) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Lege input- en output-mappen
        _add_empty_dir(zf, f"{ZIP_ROOT}/input")
        _add_empty_dir(zf, f"{ZIP_ROOT}/output")

        # Root-bestanden
        for name in ROOT_FILES:
            src = ROOT / name
            if not src.exists():
                print(f"  Waarschuwing: {name} niet gevonden, overgeslagen.")
                continue
            zf.write(src, f"{ZIP_ROOT}/{name}")
            print(f"  + {name}")

        # Converter-mappen
        for dirname in CONVERTER_DIRS:
            src_dir = ROOT / dirname
            if not src_dir.is_dir():
                print(f"  Waarschuwing: map {dirname}/ niet gevonden, overgeslagen.")
                continue
            added = 0
            for src in sorted(src_dir.iterdir()):
                if src.suffix in (".py", ".html"):
                    zf.write(src, f"{ZIP_ROOT}/{dirname}/{src.name}")
                    print(f"  + {dirname}/{src.name}")
                    added += 1
            if added == 0:
                print(f"  Waarschuwing: geen .py/.html bestanden in {dirname}/")

    size_kb = output_path.stat().st_size // 1024
    print(f"\nKlaar: {output_path.name} ({size_kb} KB)")


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from version import VERSION

    output_path = ROOT / f"infosphere-converters-{VERSION}.zip"

    if output_path.exists():
        output_path.unlink()
        print(f"Bestaand bestand verwijderd: {output_path.name}")

    print(f"Versie : {VERSION}")
    print(f"Uitvoer: {output_path.name}\n")

    build(output_path, VERSION)


if __name__ == "__main__":
    main()
