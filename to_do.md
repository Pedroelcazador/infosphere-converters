# To-do: verbeterpunten Infosphere Converters

Bijgewerkt op 2026-03-04.

---

## Hoog

### 1. ~~Path traversal in web UI~~ ✅ OPGELOST
**Bestand:** `web_ui.py` — `/output/` endpoint

`(OUTPUT_DIR / fname).resolve()` + `is_relative_to()` check toegevoegd. Requests buiten de output-map worden geweigerd.

---

### 2. ~~Regex bug bij lijst-items~~ ✅ OPGELOST
**Bestand:** `md_to_html.py`

Backslash-in-f-string fout is hersteld. Regex gecompileerd buiten de f-string als `_list_pat`.

---

### 3. ~~Module-import pattern in converters (sys.modules.pop / sys.path.insert)~~ ✅ OPGELOST
**Bestanden:** `msl_lineage/msl_lineage.py`, `ds_flow/ds_flow.py`

Beide scripts laden nu hun zustermodule via `importlib.util.spec_from_file_location()` + `exec_module()`. `sys.path.insert()` is verwijderd; `sys.modules` wordt alleen nog gebruikt om de geladen module te registreren (zodat `find_msl_file` en andere geïmporteerde functies hun globals correct kunnen vinden).

---

## Middel

### 4. Gesplitste converter-registry
**Bestanden:** `main.py` (MENU), `web_ui.py` (CONVERTERS, AUTO_RUN, TAB_LABELS, CONV_OUTPUT_SUFFIX)

Elke nieuwe converter vereist aanpassingen op vijf verschillende plekken in twee bestanden.

**Oplossing:** Centraliseer in één `converters.py` met één datastructuur per converter, geïmporteerd door zowel `main.py` als `web_ui.py`.

---

### 5. Globale state-mutatie in run_conversion
**Bestand:** `web_ui.py`

`sys.argv` en `logging.root.handlers` worden globaal aangepast bij elke conversie. Niet thread-safe: gelijktijdige requests zouden elkaar corrumperen.

**Momenteel geen probleem** omdat `HTTPServer` single-threaded is. Bij overstap naar `ThreadingHTTPServer` wordt dit een bug.

**Oplossing:** geef het scriptpad als argument aan `main(path)`, zodat `sys.argv`-manipulatie niet nodig is.

---

### 6. ~~Geen bestandsgroottelimiet bij uploads~~ ✅ OPGELOST
**Bestand:** `web_ui.py`

`MAX_UPLOAD = 50 MB` gedefinieerd. Uploads boven de limiet krijgen een duidelijke foutmelding.

---

### 7. Regex voor XML-parsing in ds_convert
**Bestand:** `ds_convert/ds_convert.py`

Jobs, Records en Properties worden grotendeels via regex geparsed. Fragiel bij CDATA-secties, attributen op meerdere regels en geneste elementen. `msl_convert.py` en `ldm_convert.py` gebruiken consequent `xml.etree.ElementTree`.

**Oplossing:** vervang regex-based XML-parsing door `ElementTree`, consistent met de andere converters.

**Uitgesteld:** `prop()` wordt 51 keer aangeroepen in 727 regels. Een volledige omzetting raakt elk render-functie en vereist dedicated planning. De huidige regex-aanpak werkt correct voor geldige DataStage DSExport XML. Aanpakken nadat smoke-tests zijn uitgebreid met gevallen die CDATA en multi-line attributen testen.

---

### 8. Stage-rendering duplicatie in ds_convert
**Bestand:** `ds_convert/ds_convert.py`

`render_container()` en `render_parallel_job()` bevatten vrijwel identieke stage-rendering logica (~40 regels). Wijzigingen moeten op twee plekken doorgevoerd worden.

**Oplossing:** extraheer naar een gedeelde `render_stages(records, out)` hulpfunctie.

---

## Laag

### 9. make_anchor() staat op drie plekken
**Bestanden:** `ds_convert/ds_convert.py`, `msl_convert/msl_convert.py`, `md_to_html.py`

Vrijwel identieke implementatie. Als de logica wijzigt, moet het op drie plekken worden aangepast.

**Oplossing:** verplaats naar `md_to_html.py` en importeer vanuit de converters.

---

### 10. ~~Misbruik van list comprehensions als statements~~ ✅ OPGELOST
**Bestand:** `web_ui.py`

Vervangen door gewone `for`-loops.

---

### 11. Geen tests
Er is geen test-suite. Converters zijn complexe transformaties waarbij regressies snel kunnen optreden.

**Oplossing:** voeg minimaal smoke-tests toe met een kleine voorbeeld-XML/MSL per converter (bijv. met `unittest` of `pytest`).

---

## Overzicht

| # | Prioriteit | Bestand | Omschrijving | Status |
|---|---|---|---|---|
| 1 | Hoog | `web_ui.py` | Path traversal bij bestandsservering | ✅ Opgelost |
| 2 | Hoog | `md_to_html.py` | Regex bug bij lijst-items | ✅ Opgelost |
| 3 | Hoog | `msl_lineage.py`, `ds_flow.py` | sys.modules.pop / sys.path.insert pattern | ✅ Opgelost |
| 4 | Middel | `main.py` / `web_ui.py` | Gesplitste converter-registry | ✅ Opgelost |
| 5 | Middel | `web_ui.py` | Globale state-mutatie (sys.argv / logging) | ✅ Opgelost (sys.argv) |
| 6 | Middel | `web_ui.py` | Geen uploadlimiet | ✅ Opgelost |
| 7 | Middel | `ds_convert.py` | Regex i.p.v. XML-parser | ⚠️ Uitgesteld |
| 8 | Middel | `ds_convert.py` | Stage-rendering duplicatie | ✅ Opgelost |
| 9 | Laag | meerdere bestanden | `make_anchor()` duplicatie | ✅ Opgelost |
| 10 | Laag | `web_ui.py` | List comprehension als statement | ✅ Opgelost |
| 11 | Laag | — | Geen tests | ✅ Opgelost |
