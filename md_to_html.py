#!/usr/bin/env python3
# Versie: 2026-02-27 10:00
"""
md_to_html.py — Verbeterde Markdown → HTML converter voor DIM documentatie.
Oplossing voor de backslash-fout bij geconcateneerde velden in tabellen.
"""

import re
import html as _html
from typing import Optional

# ---------------------------------------------------------------------------
# CSS + HTML template (Ongewijzigd conform origineel)
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --bg:         #f5f7fa;
  --sidebar-bg: #1e2a3a;
  --sidebar-w:  260px;
  --accent:     #2563eb;
  --accent-lt:  #dbeafe;
  --text:       #1a202c;
  --muted:      #6b7280;
  --border:     #d1d5db;
  --code-bg:    #f1f5f9;
  --sql-bg:     #0f172a;
  --th-bg:      #e8edf5;
  --dim-bg:     #f8fafc;
  --radius:     6px;
  --shadow:     0 1px 4px rgba(0,0,0,.12);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.65;
  color: var(--text);
  background: var(--bg);
  display: flex;
}

#sidebar {
  position: fixed;
  top: 0; left: 0;
  width: var(--sidebar-w);
  height: 100vh;
  background: var(--sidebar-bg);
  overflow-y: auto;
  padding: 20px 0 40px;
  z-index: 100;
}

#sidebar .sidebar-title {
  color: #94a3b8;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
  padding: 0 16px 12px;
  border-bottom: 1px solid #2d3f55;
  margin-bottom: 8px;
}

#sidebar a {
  display: block;
  color: #cbd5e1;
  text-decoration: none;
  padding: 5px 16px;
  font-size: 12.5px;
  border-left: 3px solid transparent;
  transition: all .15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

#sidebar a:hover,
#sidebar a.active {
  color: #fff;
  background: rgba(255,255,255,.06);
  border-left-color: var(--accent);
}

#sidebar a.nav-h1 { font-weight: 700; font-size: 13px; margin-top: 10px; color: #e2e8f0; }
#sidebar a.nav-h2 { padding-left: 24px; }
#sidebar a.nav-h3 { padding-left: 36px; font-size: 12px; color: #94a3b8; }
#sidebar a.nav-h4 { padding-left: 48px; font-size: 11.5px; color: #64748b; }

#content {
  margin-left: var(--sidebar-w);
  padding: 32px 48px 80px;
  max-width: 1100px;
  width: 100%;
  min-height: 100vh;
}

h1 { font-size: 1.75em; border-bottom: 2px solid var(--accent); padding-bottom: 8px; margin: 28px 0 16px; color: #0f172a; }
h2 { font-size: 1.35em; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin: 24px 0 12px; color: #1e293b; }
h3 { font-size: 1.1em; margin: 20px 0 8px; color: #334155; }
h4 { font-size: .95em; margin: 16px 0 6px; color: #475569; font-weight: 600; }

table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0 20px;
  font-size: 13px;
  box-shadow: var(--shadow);
  border-radius: var(--radius);
  overflow: hidden;
}

thead th {
  background: var(--th-bg);
  font-weight: 600;
  padding: 9px 12px;
  text-align: left;
  border-bottom: 2px solid var(--border);
  white-space: nowrap;
}

thead th.center { text-align: center; }
thead th.right  { text-align: right;  }

tbody tr:nth-child(even) { background: #f8fafc; }
tbody tr:hover           { background: #eff6ff; }

td {
  padding: 7px 12px;
  border-bottom: 1px solid #edf0f4;
  vertical-align: top;
}

td.center { text-align: center; }
td.right  { text-align: right;  }

code {
  background: var(--code-bg);
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  padding: 1px 5px;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: .87em;
  color: #be185d;
}

pre {
  background: var(--sql-bg);
  color: #e2e8f0;
  border-radius: var(--radius);
  padding: 16px 20px;
  overflow-x: auto;
  margin: 12px 0 20px;
  font-size: 12.5px;
  line-height: 1.6;
  box-shadow: var(--shadow);
}

pre code {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}

.code-block {
  position: relative;
  margin: 12px 0 20px;
}
.code-block pre {
  margin: 0;
}
.copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(255,255,255,.08);
  border: 1px solid rgba(255,255,255,.15);
  color: #94a3b8;
  border-radius: 4px;
  padding: 3px 9px;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: opacity .15s, background .15s;
  font-family: inherit;
}
.code-block:hover .copy-btn { opacity: 1; }
.copy-btn:hover { background: rgba(255,255,255,.15); color: #e2e8f0; }
.copy-btn.copied { color: #86efac; border-color: #86efac; }

.kw  { color: #7dd3fc; font-weight: 600; }
.str { color: #86efac; }
.cmt { color: #64748b; font-style: italic; }
.num { color: #fca5a5; }
.fn  { color: #c4b5fd; }

details {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin: 8px 0 16px;
  background: var(--dim-bg);
}

summary {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}

summary:hover { color: var(--accent); }
details[open] summary { border-bottom: 1px solid var(--border); }
details > *:not(summary) { padding: 0 14px; }
details table { margin: 12px 0; }

hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 28px 0;
}

p  { margin: 8px 0; }
em { font-style: italic; color: var(--muted); }
strong { font-weight: 700; }

ul, ol { margin: 6px 0 6px 20px; }
li { margin: 2px 0; }

[id]::before {
  content: '';
  display: block;
  height: 70px;
  margin-top: -70px;
  visibility: hidden;
}

#sidebar::-webkit-scrollbar { width: 4px; }
#sidebar::-webkit-scrollbar-thumb { background: #3d5068; border-radius: 2px; }

@media (max-width: 768px) {
  #sidebar { display: none; }
  #content { margin-left: 0; padding: 16px; }
}
"""

_JS = """
(function() {
  const links = document.querySelectorAll('#sidebar a[href^="#"]');
  const sections = [];
  links.forEach(a => {
    const id = a.getAttribute('href').slice(1);
    const el = document.getElementById(id);
    if (el) sections.push({ id, el, a });
  });

  function onScroll() {
    const top = window.scrollY + 80;
    let active = null;
    for (const s of sections) {
      if (s.el.offsetTop <= top) active = s;
    }
    links.forEach(a => a.classList.remove('active'));
    if (active) active.a.classList.add('active');
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Copy-knop voor codeblokken
  document.querySelectorAll('.code-block').forEach(block => {
    const btn = block.querySelector('.copy-btn');
    const code = block.querySelector('code');
    btn.addEventListener('click', () => {
      const text = code.innerText;
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✓ Gekopieerd';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = 'Kopieer';
          btn.classList.remove('copied');
        }, 2000);
      });
    });
  });
})();
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>

<nav id="sidebar">
  <div class="sidebar-title">Navigatie</div>
{nav}
</nav>

<main id="content">
{body}
</main>

<script>{js}</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# SQL syntax highlighting
# ---------------------------------------------------------------------------

_SQL_KW = re.compile(
    r'\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|AND|OR|NOT|IN|'
    r'EXISTS|BETWEEN|LIKE|IS|NULL|AS|DISTINCT|GROUP\s+BY|ORDER\s+BY|HAVING|'
    r'UNION|ALL|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|VIEW|INDEX|'
    r'DROP|ALTER|ADD|COLUMN|CONSTRAINT|PRIMARY|KEY|FOREIGN|REFERENCES|WITH|'
    r'CASE|WHEN|THEN|ELSE|END|OVER|PARTITION\s+BY|MERGE|USING|MATCHED|'
    r'COMMIT|ROLLBACK|TRUNCATE|EXECUTE|EXEC|PROCEDURE|FUNCTION|TRIGGER|'
    r'BEGIN|DECLARE|RETURN|IF|ELSE|WHILE|CONNECT|BY)\b',
    re.IGNORECASE
)

_SQL_STR = re.compile(r"'(?:[^'\\]|\\.)*'")
_SQL_CMT_LINE  = re.compile(r'--[^\n]*')
_SQL_CMT_BLOCK = re.compile(r'/\*.*?\*/', re.DOTALL)
_SQL_NUM  = re.compile(r'\b\d+(?:\.\d+)?\b')
_SQL_FN   = re.compile(r'\b(NVL|NVL2|DECODE|COALESCE|CASE|TO_DATE|TO_CHAR|TO_NUMBER|'
                       r'TRIM|LTRIM|RTRIM|UPPER|LOWER|SUBSTR|INSTR|LENGTH|REPLACE|'
                       r'SYSDATE|SYSTIMESTAMP|ROWNUM|COUNT|SUM|MIN|MAX|AVG|'
                       r'ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD|LISTAGG)\b', re.IGNORECASE)

def _highlight_sql(code: str) -> str:
    protected: list[tuple[int, int, str]] = []
    for m in _SQL_CMT_BLOCK.finditer(code):
        protected.append((m.start(), m.end(), f'<span class="cmt">{_html.escape(m.group())}</span>'))
    for m in _SQL_CMT_LINE.finditer(code):
        if not any(s <= m.start() < e for s, e, _ in protected):
            protected.append((m.start(), m.end(), f'<span class="cmt">{_html.escape(m.group())}</span>'))
    for m in _SQL_STR.finditer(code):
        if not any(s <= m.start() < e for s, e, _ in protected):
            protected.append((m.start(), m.end(), f'<span class="str">{_html.escape(m.group())}</span>'))

    protected.sort(key=lambda x: x[0], reverse=True)
    result = code
    for start, end, replacement in protected:
        result = result[:start] + '\x00' + replacement + '\x01' + result[end:]

    parts = re.split(r'\x00(.*?)\x01', result)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            p = _html.escape(part)
            p = _SQL_FN.sub(lambda m: f'<span class="fn">{m.group()}</span>', p)
            p = _SQL_KW.sub(lambda m: f'<span class="kw">{m.group()}</span>', p)
            p = _SQL_NUM.sub(lambda m: f'<span class="num">{m.group()}</span>', p)
            out.append(p)
        else:
            out.append(part)
    return ''.join(out)

# ---------------------------------------------------------------------------
# Markdown → HTML converter (Verbeterde Table Logic)
# ---------------------------------------------------------------------------

def make_anchor(text: str) -> str:
    """Genereer een HTML anchor-naam (spaties/underscores → koppelteken, rest verwijderd)."""
    return re.sub(r'[^a-z0-9\-]', '', text.lower().replace(' ', '-').replace('_', '-'))

def _anchor_id(text: str) -> str:
    return make_anchor(re.sub(r'<[^>]+>', '', text))

def _inline(text: str) -> str:
    """Verwerk inline Markdown en herstel geëscapete pipes."""
    parts = re.split(r'(<[^>]+>)', text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            out.append(part)
        else:
            p = _html.escape(part, quote=False)
            # CRUCIAAL: Herstel geëscapete pipes (\| -> |) NADAT de tabel is gesplitst
            p = p.replace('\\|', '|')
            p = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', p)
            p = re.sub(r'\*(.+?)\*', r'<em>\1</em>', p)
            p = re.sub(r'`([^`]+)`', r'<code>\1</code>', p)
            p = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', p)
            out.append(p)
    return ''.join(out)

def _parse_table(lines: list[str]) -> str:
    """
    Zet een Markdown-tabel om naar HTML.
    Gebruikt regex om escaped pipes (\\|) te negeren tijdens het splitsen.
    """
    if len(lines) < 2:
        return '<p>' + _inline(lines[0]) + '</p>'

    # Regex voor splitsen op | die NIET wordt voorafgegaan door een \
    pipe_regex = re.compile(r'(?<!\\)\|')

    def clean_split(row):
        # Strip leidende/sluitende pipes en split op basis van regex
        row = row.strip().strip('|')
        return [c.strip() for c in pipe_regex.split(row)]

    header = clean_split(lines[0])
    sep    = clean_split(lines[1])
    rows   = [clean_split(ln) for ln in lines[2:]]

    aligns = []
    for s in sep:
        if s.startswith(':') and s.endswith(':'): aligns.append('center')
        elif s.endswith(':'): aligns.append('right')
        else: aligns.append('')

    html_lines = ['<table>', '<thead><tr>']
    for i, h in enumerate(header):
        al = f' class="{aligns[i]}"' if i < len(aligns) and aligns[i] else ''
        html_lines.append(f'<th{al}>{_inline(h)}</th>')
    html_lines.append('</tr></thead><tbody>')

    for row in rows:
        html_lines.append('<tr>')
        for i, cell in enumerate(row):
            al = f' class="{aligns[i]}"' if i < len(aligns) and aligns[i] else ''
            html_lines.append(f'<td{al}>{_inline(cell)}</td>')
        for i in range(len(row), len(header)):
            html_lines.append('<td></td>')
        html_lines.append('</tr>')

    html_lines.append('</tbody></table>')
    return '\n'.join(html_lines)

def md_to_html(md_text: str, title: str = 'DIM Documentatie') -> str:
    lines = md_text.splitlines()
    body_parts: list[str] = []
    nav_links:  list[str] = []
    anchor_counts: dict[str, int] = {}  # bijhouden hoeveel keer een base-anchor al gebruikt is

    def unique_anchor(base: str) -> str:
        if base not in anchor_counts:
            anchor_counts[base] = 1
            return base
        else:
            anchor_counts[base] += 1
            return f'{base}-{anchor_counts[base]}'

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('```'):
            lang = line.strip()[3:].lower().strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i]); i += 1
            code = '\n'.join(code_lines)
            highlighted = _highlight_sql(code) if lang == 'sql' else _html.escape(code)
            body_parts.append(f'<div class="code-block"><button class="copy-btn">Kopieer</button><pre><code class="lang-{lang}">{highlighted}</code></pre></div>')
            i += 1; continue
        if line.strip().lower().startswith('<details'):
            detail_lines = [line]; i += 1
            while i < len(lines):
                detail_lines.append(lines[i])
                if lines[i].strip().lower() == '</details>': i += 1; break
                i += 1
            body_parts.append(_process_details_content(detail_lines)); continue
        if re.match(r'^-{3,}\s*$', line) or re.match(r'^={3,}\s*$', line):
            body_parts.append('<hr>'); i += 1; continue
        hm = re.match(r'^(#{1,4})\s+(.*)', line)
        if hm:
            level = len(hm.group(1)); text = hm.group(2).strip()
            anchor = unique_anchor(_anchor_id(text))
            clean = re.sub(r'<[^>]+>', '', _inline(text))
            body_parts.append(f'<h{level} id="{anchor}">{_inline(text)}</h{level}>')
            nav_links.append(f'  <a href="#{anchor}" class="nav-h{level}">{_html.escape(clean)}</a>')
            i += 1; continue
        if '|' in line and i + 1 < len(lines) and re.match(r'^\s*\|?[\s:|-]+\|', lines[i + 1]):
            table_lines = [line]; j = i + 1
            while j < len(lines) and '|' in lines[j]:
                table_lines.append(lines[j]); j += 1
            body_parts.append(_parse_table(table_lines)); i = j; continue
        if re.match(r'^[\s]*[-*]\s+', line):
            list_lines = [line]; j = i + 1
            while j < len(lines) and re.match(r'^[\s]*[-*]\s+', lines[j]):
                list_lines.append(lines[j]); j += 1
            _list_pat = re.compile(r'^[\s]*[-*]\s+')
            items = [f'<li>{_inline(_list_pat.sub("", ll))}</li>' for ll in list_lines]
            body_parts.append('<ul>' + ''.join(items) + '</ul>'); i = j; continue
        if not line.strip(): i += 1; continue
        if re.match(r'^\s*<[a-zA-Z/]', line):
            body_parts.append(line); i += 1; continue
        body_parts.append(f'<p>{_inline(line)}</p>'); i += 1
    return _HTML_TEMPLATE.format(title=_html.escape(title), css=_CSS, js=_JS, nav='\n'.join(nav_links), body='\n'.join(body_parts))

def _process_details_content(detail_lines: list[str]) -> str:
    out = []; i = 0
    while i < len(detail_lines):
        line = detail_lines[i]
        if '|' in line and i + 1 < len(detail_lines) and re.match(r'^\s*\|?[\s:|-]+\|', detail_lines[i + 1]):
            table_lines = [line]; j = i + 1
            while j < len(detail_lines) and '|' in detail_lines[j]:
                table_lines.append(detail_lines[j]); j += 1
            out.append(_parse_table(table_lines)); i = j
        elif line.strip().startswith('```'):
            lang = line.strip()[3:].lower().strip(); code_lines = []; i += 1
            while i < len(detail_lines) and not detail_lines[i].strip().startswith('```'):
                code_lines.append(detail_lines[i]); i += 1
            code = '\n'.join(code_lines)
            highlighted = _highlight_sql(code) if lang == 'sql' else _html.escape(code)
            out.append(f'<div class="code-block"><button class="copy-btn">Kopieer</button><pre><code class="lang-{lang}">{highlighted}</code></pre></div>'); i += 1
        else:
            stripped = line.strip()
            out.append(line if stripped.startswith('<') or stripped == '' else f'<p>{_inline(line)}</p>')
            i += 1
    return '\n'.join(out)

if __name__ == '__main__':
    import sys
    from pathlib import Path
    if len(sys.argv) < 2:
        print("Gebruik: python md_to_html.py input.md [output.html]")
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix('.html')
    md = src.read_text(encoding='utf-8')
    dst.write_text(md_to_html(md, title=src.stem.replace('_', ' ')), encoding='utf-8')
    print(f"✓ {src.name} → {dst.name}")