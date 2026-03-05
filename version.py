"""
Versienummer: yyyymmddvN
N = aantal git commits op de huidige dag (minimaal 1).
Wordt eenmalig berekend bij import.
"""

import subprocess
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _compute() -> str:
    today = datetime.now().strftime('%Y%m%d')
    date_fmt = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    try:
        result = subprocess.run(
            ['git', 'log', '--oneline',
             f'--after={date_fmt} 00:00:00',
             f'--before={date_fmt} 23:59:59'],
            capture_output=True, text=True,
            cwd=str(_ROOT), timeout=3
        )
        n = len([l for l in result.stdout.splitlines() if l.strip()])
    except Exception:
        n = 0
    return f"{today}v{max(n, 1)}"


VERSION = _compute()
