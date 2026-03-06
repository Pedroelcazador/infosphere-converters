# To-do: verbeterpunten Infosphere Converters

Bijgewerkt op 2026-03-05 (item 13 toegevoegd).

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

### 7. ~~Regex voor XML-parsing in ds_convert~~ ✅ OPGELOST
**Bestanden:** `ds_convert/ds_convert.py`, `ds_flow/ds_flow.py`

`prop()`, `split_jobs()`, `split_containers()`, `get_records()`, `get_job_header()`,
`get_annotations()`, `get_custom_props()`, `get_xmlprops_tree()` en `validate_dse()`
gebruiken nu allemaal `xml.etree.ElementTree`. ET handelt CDATA en XML-entities
transparant af — de CDATA-strips en `html.unescape()`-aanroepen op property-waarden
zijn verwijderd. `ds_flow.py` bijgewerkt om mee te liften op de nieuwe ET-API.
Regels die intern de DataStage `\(N)`-notatie parsen (`parse_px_keys`, `parse_px_reduce`,
`parse_px_modifyspec`) gebruiken bewust regex — dat is geen XML.
Smoke-tests uitgebreid met CDATA- en HTML-entity-fixtures.

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

## Uitbreiding

### 12. DataStage Linter (ds_linter.py)
**Bestand:** nieuw — `ds_linter/ds_linter.py`

Nieuwe module die actieve kwaliteitscontroles (QA) uitvoert op geëxporteerde DataStage XML-bestanden en een HTML-rapport genereert.

**Architectuur:**
- Laadt parsing-logica uit `ds_convert.py` via `importlib` (zoals `ds_flow.py` dat doet)
- Rule-engine: elke check retourneert `Pass / Warning / Critical` + toelichting
- Output: `<naam>_QAReport.html`
- Registratie in `converters.py` als `file_type: 'dsexport'`, tab-label `QA Rapport`

**Initiële checks (nog uit te breiden — eerst volledige lijst verzamelen):**

| # | Niveau | Check |
|---|---|---|
| C1 | Kritiek | Oracle Target WriteMode = 6 (BULK LOAD) |
| C2 | Kritiek | FailOnRowErrorPX niet op 0/False — geruisloos weggooien is integriteitsrisico; default-waarde eerst verifiëren |
| C3 | Waarschuwing | ≥ 4 TransformerStage/PxTransformer per parallel job — adviseer Copy of Modify |
| C4 | Waarschuwing | ROOT-record mist Description / FullDescription |
| C5 | Waarschuwing | Stagenamen volgen geen prefix-conventie (`orc_`, `trn_`, `agg_`, `jnr_`) — configureerbaar maken |
| C6 | Waarschuwing | Ontkoppelde stages zonder input- of output-verbinding (wees-stages) |

**Openstaande vragen vóór implementatie:**
- Wat is de DataStage-default van `FailOnRowErrorPX` bij ontbrekende property?
- Is WriteMode=9 (UPSERT/MERGE) ook acceptabel voor C1, of altijd kritiek?
- Drempel C3: is 4 transformers de juiste grens, of liever op derivations per transformer?
- Welke aanvullende checks zijn relevant? (lijst verzamelen vóór start)

---

### 13. Interne job flow bekijken vanuit sequencer-view
**Bestanden:** `ds_flow/ds_flow.py` (uitbreiding)

Wanneer een sequencer-export ook de definities van de aangeroepen parallel jobs bevat, is het niet mogelijk om de interne stage-diagram van een individuele job te bekijken vanuit de sequencer-view.

**Voorkeur aanpak (Optie A — alles in één HTML):**
`ds_flow.py` genereert naast de sequencer-tab(s) ook een tab per parallel job, met de interne stage-diagram (op basis van de logica in `ds_job_flow.py`). Alles in één HTML-bestand; de gebruiker navigeert met één klik van de sequencer-view naar een job-view.

**Alternatieve aanpakken:**
- **Optie B:** "Bekijk job flow"-knop in het detail-paneel opent een apart gegenereerd `_JobFlow.html` per job in een nieuw browservenster. Minder code in `ds_flow.py`, maar produceert meerdere losse bestanden.
- **Optie C:** Aparte converter-run in de web UI (`ds_job_flow.py` uitbreiden voor meerdere jobs tegelijk, met dropdown-selector). Minste wijziging in `ds_flow.py`, maar vereist uitbreiding van `ds_job_flow.py` en de converter-registry.

**Openstaande vragen vóór implementatie:**
- Welke aanpak heeft voorkeur (A, B of C)?
- Bij Optie A: aparte tabgroep voor job-flows, of mixed in de huidige sequencer-tab-balk?
- Alleen jobs met OracleConnectorPX-stages tonen, of álle parallel jobs?

---

## Bewust niet opgepakt

De onderstaande punten zijn bekende architectuurkwesties. Ze zijn beoordeeld en bewust buiten scope gehouden zolang de huidige context (intern, single-user, stabiel) niet verandert.

### A. `__init__.py` ontbreekt in converter-mappen
Converter-mappen (`ds_convert/`, `msl_convert/`, etc.) hebben geen `__init__.py`. Python 3.3+ behandelt ze daardoor als *implicit namespace packages*, wat een naming conflict veroorzaakt als `ROOT_DIR` in `sys.path` staat. Huidig workaround: `importlib.util.spec_from_file_location()` in `web_ui.py`.

**Waarom niet opgepakt:** vereist refactoring van de laadroutine in `web_ui.py` met nul zichtbaar voordeel voor de gebruiker. Oppakken als de codebase flink wordt uitgebreid of als het conflict daadwerkelijk problemen geeft.

### B. `subprocess.run()` in `main.py`
Het CLI-menu start converters als losse subprocessen. `web_ui.py` gebruikt daarentegen `importlib`. Inconsistent, maar niet problematisch.

**Waarom niet opgepakt:** de CLI is de secundaire interface. Subprocess-isolatie heeft zelfs een voordeel: een crashende converter gooit het menu niet omver. Overstappen naar importlib voegt niets toe.

### C. Globale state-mutatie in `web_ui.py`
`logging.root.handlers` wordt tijdelijk aangepast tijdens een conversie. Niet thread-safe.

**Waarom niet opgepakt:** `HTTPServer` is single-threaded, één gebruiker tegelijk. Pas relevant als de server ooit multi-threaded wordt — dat staat niet op de roadmap. Bij scope-verandering: geef logging-context mee als parameter i.p.v. globale state te muteren.

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
| 7 | Middel | `ds_convert.py`, `ds_flow.py` | Regex i.p.v. XML-parser | ✅ Opgelost |
| 8 | Middel | `ds_convert.py` | Stage-rendering duplicatie | ✅ Opgelost |
| 9 | Laag | meerdere bestanden | `make_anchor()` duplicatie | ✅ Opgelost |
| 10 | Laag | `web_ui.py` | List comprehension als statement | ✅ Opgelost |
| 11 | Laag | — | Geen tests | ✅ Opgelost |
| 12 | Uitbreiding | `ds_linter/ds_linter.py` | DataStage Linter / QA-rapport | ⏳ Checklist verzamelen |
| 13 | Uitbreiding | `ds_flow/ds_flow.py` | Interne job flow bekijken vanuit sequencer-view | ⏳ Aanpak kiezen |
