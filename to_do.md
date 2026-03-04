# To-do: verbeterpunten Infosphere Converters

Gegenereerd op basis van codeanalyse op 2026-03-03.

---

## Hoog

### 1. Path traversal in web UI
**Bestand:** `web_ui.py:196`

Een request naar `/output/../../etc/passwd` kan buiten `output/` uitkomen. Er wordt niet gecontroleerd of het gevraagde bestand daadwerkelijk binnen `OUTPUT_DIR` ligt.

```python
# Huidig
fpath = OUTPUT_DIR / fname
if fpath.exists() and fpath.is_file():
    ...

# Oplossing: voeg toe
if not fpath.resolve().is_relative_to(OUTPUT_DIR):
    self._send(404, "text/plain", b"Niet gevonden")
    return
```

---

### 2. Regex bug bij lijst-items
**Bestand:** `md_to_html.py:495`

In de raw string `r"^[\\s]*[-*]\\s+"` matcht `[\\s]` letterlijk een backslash of `s`, niet whitespace. Dit leidt tot incorrecte verwerking van lijst-items.

```python
# Huidig (fout)
re.sub(r"^[\\s]*[-*]\\s+", "", ll)

# Correct
re.sub(r"^\s*[-*]\s+", "", ll)
```

---

## Middel

### 3. Stage-rendering duplicatie in ds_convert
**Bestand:** `ds_convert.py:519–550` en `553–596`

`render_container()` en `render_parallel_job()` bevatten vrijwel identieke stage-rendering logica (±40 regels). Wijzigingen moeten op twee plekken doorgevoerd worden.

**Oplossing:** Extraheer naar een gedeelde `render_stages(records, out)` hulpfunctie.

---

### 4. Gesplitste converter-registry
**Bestanden:** `main.py` (MENU), `web_ui.py` (CONVERTERS, AUTO_RUN, TAB_LABELS, CONV_OUTPUT_SUFFIX)

Elke nieuwe converter vereist aanpassingen op vijf verschillende plekken verspreid over twee bestanden.

**Oplossing:** Centraliseer in één `converters.py` met één datastructuur per converter.

---

### 5. Globale state-mutatie in run_conversion
**Bestand:** `web_ui.py:114`

`sys.argv` en `logging.root.handlers` worden globaal gemuteerd tijdens een conversie. Niet thread-safe: gelijktijdige requests corrumperen elkaar.

```python
# Huidig
old = sys.argv[:]; sys.argv = [str(sp)]
# ... run module ...
sys.argv = old
```

**Oplossing:** Geef het script-pad als argument mee aan `main()` zodat `sys.argv`-manipulatie niet nodig is.

---

### 6. Geen bestandsgroottelimiet bij uploads
**Bestand:** `web_ui.py:212`

`Content-Length` wordt zonder limiet gelezen. Een grote upload kan de server laten crashen door geheugenuitputting.

```python
# Oplossing: voeg een maximum toe
MAX_UPLOAD = 50 * 1024 * 1024  # 50 MB
if cl > MAX_UPLOAD:
    self._json({"error": "Bestand te groot (max 50 MB)", "tabs": [], "log": ""})
    return
```

---

### 7. Regex voor XML-parsing in ds_convert
**Bestand:** `ds_convert.py`

Jobs, Records en Properties worden grotendeels via regex geparsed. Fragiel bij CDATA-secties, attributen op meerdere regels en geneste elementen. `msl_convert.py` en `ldm_convert.py` gebruiken al consequent `xml.etree.ElementTree`.

**Oplossing:** Vervang regex-based XML-parsing door `ElementTree`, consistent met de andere converters. De twee functies `prop()` en `xprop()` naast elkaar bestaan omdat de verwerking nu inconsistent is.

---

## Laag

### 8. make_anchor() staat op drie plekken
**Bestanden:** `ds_convert.py:32`, `msl_convert.py:47`, `md_to_html.py:376`

Vrijwel identieke implementatie. Als de logica wijzigt, moet het op drie plekken worden aangepast.

**Oplossing:** Verplaats naar `md_to_html.py` en importeer vanuit de converters.

---

### 9. Misbruik van list comprehensions als statements
**Bestand:** `web_ui.py:95–96`

```python
# Huidig — bouwt een lijst op die direct weggegooid wordt
[f2.unlink() for f2 in list(INPUT_DIR.iterdir()) if f2.is_file()]

# Correct
for f2 in INPUT_DIR.iterdir():
    if f2.is_file():
        f2.unlink()
```

---

### 10. Geen tests
Er is geen test-suite. Converters zijn complexe transformaties waarbij regressies snel kunnen optreden.

**Oplossing:** Voeg minimaal smoke-tests toe met een kleine voorbeeld-XML/MSL per converter (bijv. met `unittest` of `pytest`).

---

## Overzicht

| # | Prioriteit | Bestand | Omschrijving |
|---|---|---|---|
| 1 | Hoog | `web_ui.py:196` | Path traversal bij bestandsservering |
| 2 | Hoog | `md_to_html.py:495` | Regex bug bij lijst-items |
| 3 | Middel | `ds_convert.py:488–596` | Stage-rendering duplicatie |
| 4 | Middel | `main.py` / `web_ui.py` | Gesplitste converter-registry |
| 5 | Middel | `web_ui.py:114` | Globale state-mutatie (sys.argv / logging) |
| 6 | Middel | `web_ui.py:212` | Geen uploadlimiet |
| 7 | Middel | `ds_convert.py` | Regex i.p.v. XML-parser |
| 8 | Laag | meerdere bestanden | `make_anchor()` duplicatie |
| 9 | Laag | `web_ui.py:95` | List comprehension als statement |
| 10 | Laag | — | Geen tests |
