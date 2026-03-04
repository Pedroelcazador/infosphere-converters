#!/usr/bin/env python3
# Versie: 2026-03-01 12:00
"""
Infosphere Converters — hoofdmenu

Gebruik:
  python3 main.py

Zet het inputbestand in de input/ map en kies een conversie.
Uitvoer verschijnt in de output/ map.
"""

import sys
import subprocess
from pathlib import Path

ROOT_DIR   = Path(__file__).resolve().parent
INPUT_DIR  = ROOT_DIR / 'input'
OUTPUT_DIR = ROOT_DIR / 'output'

from converters import REGISTRY as _REGISTRY
MENU = [
    (c['menu_label'], c['name'], str(c['script'].relative_to(ROOT_DIR)))
    for c in _REGISTRY
    if c['menu_label'] and c['script']
]

LIJN  = '─' * 50
DLIJN = '═' * 50


def check_input() -> list[Path]:
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    return list(INPUT_DIR.iterdir())


def toon_menu() -> None:
    print(f'\n{DLIJN}')
    print('  Infosphere Converters')
    print(DLIJN)
    for i, (label, _, _) in enumerate(MENU, 1):
        print(f'  {i}.  {label}')
    print(f'  0.  Afsluiten')
    print(LIJN)


def toon_input_status(bestanden: list[Path]) -> None:
    if not bestanden:
        print(f'  ⚠  Geen bestand in input/ gevonden.')
    else:
        namen = ', '.join(f.name for f in bestanden)
        print(f'  📄 Input: {namen}')
    print(LIJN)


def run_script(script_rel: str) -> None:
    script_path = ROOT_DIR / script_rel
    if not script_path.exists():
        print(f'\n  ✗  Script niet gevonden: {script_path}')
        return

    print(f'\n{LIJN}')
    print(f'  Starten: {script_path.name}')
    print(LIJN)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(ROOT_DIR),
    )

    print(LIJN)
    if result.returncode == 0:
        output_bestanden = list(OUTPUT_DIR.iterdir()) if OUTPUT_DIR.exists() else []
        if output_bestanden:
            print(f'  ✓  Klaar. Output in output/:')
            for f in sorted(output_bestanden):
                size = f.stat().st_size
                print(f'       {f.name}  ({size:,} bytes)')
        else:
            print('  ✓  Klaar.')
    else:
        print(f'  ✗  Script afgesloten met foutcode {result.returncode}.')
        print('     Controleer het logbestand in de scriptmap voor details.')
    print(LIJN)


def main() -> None:
    while True:
        bestanden = check_input()
        toon_menu()
        toon_input_status(bestanden)

        try:
            keuze = input('  Keuze: ').strip()
        except (KeyboardInterrupt, EOFError):
            print('\n\n  Tot ziens!')
            sys.exit(0)

        if keuze == '0':
            print('\n  Tot ziens!')
            sys.exit(0)

        if not keuze.isdigit() or not (1 <= int(keuze) <= len(MENU)):
            print(f'\n  ✗  Ongeldige keuze. Voer een cijfer in tussen 0 en {len(MENU)}.')
            continue

        _, _, script_rel = MENU[int(keuze) - 1]
        run_script(script_rel)

        input('\n  Druk op Enter om terug te gaan naar het menu...')


if __name__ == '__main__':
    if '--web' in sys.argv:
        from web_ui import start
        start()
        sys.exit(0)
    main()
