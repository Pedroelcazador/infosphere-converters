# CLAUDE.md — Projectcontext Infosphere Converters

Toolkit voor het omzetten van IBM InfoSphere DataStage- en IBM Data Architect-exportbestanden naar interactieve HTML en Markdown. Ontwikkeld voor het DIM-team bij UWV. Uitsluitend Python standaardbibliotheek, geen externe packages.

## Ontwerpcontext (bewuste keuzes)

- **Single-user, single-threaded.** De webserver (`HTTPServer`) is niet multi-threaded. Dat is geen omissie — de tool is bedoeld voor gebruik door één persoon tegelijk.
- **Geen externe packages.** UWV-werkstations hebben beperkte internettoegang en pip-installaties zijn administratief complex. De tool werkt out-of-the-box met alleen Python 3.10+.
- **Geen batchverwerking.** Bewust één bestand per sessie; scope is documentatie-op-aanvraag.
- **`importlib`-laden van converters (web_ui.py).** De converter-mappen hebben geen `__init__.py`. Vanaf Python 3.3 worden zulke mappen behandeld als *implicit namespace packages*: een `from msl_convert import ...` pikt de submap op in plaats van het script. `importlib.util.spec_from_file_location()` omzeilt dit correct. Alternatief zou zijn om lege `__init__.py` bestanden toe te voegen — dat lost het conflict structureel op maar is niet geïmplementeerd.
- **`main.py` gebruikt `subprocess.run()`.** Het CLI-menu start converters als losse subprocessen (`subprocess.run([sys.executable, script_path])`). Eenvoudig en geïsoleerd; foutafhandeling via returncode. `web_ui.py` gebruikt daarentegen importlib (zie boven).
- **Globale state (`sys.argv`, logging handlers).** Tijdelijke mutatie in `web_ui.py` tijdens conversie. Niet thread-safe, maar irrelevant voor single-threaded gebruik. Staat op de lijst als tech debt.

Ondersteunde bestandstypen: DSExport XML (DataStage), LDM XML (logisch datamodel), DBM XML (fysiek datamodel), MSL (attribuutmapping).

## Startpunten

- **Windows**: `start.bat` (dubbelklik, geen terminalvenster)
- **Server**: `python3 web_ui.py` → http://localhost:8080
- **CLI**: `python3 main.py`
- **Distributie-ZIP bouwen**: `python3 build_zip.py` (of dubbelklik `build_zip.bat` op Windows)

## Mapstructuur

```
infosphere-converters/
  web_ui.py               # HTTP-server (poort 8080), converter-orchestratie
  web_ui_template.html    # UI-template, ingeladen door web_ui.py bij opstart
  main.py                 # CLI-menu
  md_to_html.py           # Gedeelde module: Markdown → gestylde HTML
  start.bat               # Windows starter (pythonw, geen console)
  build_zip.py            # Bouwt distribueerbare ZIP naar dist/ (versienaam via version.py)
  build_zip.bat           # Windows wrapper voor build_zip.py (dubbelklik)
  dist/                   # Distributie-ZIPs (niet in git)
  input/                  # Één inputbestand tegelijk
  output/                 # Gegenereerde HTML/MD bestanden
  ds_convert/ds_convert.py
  ds_flow/ds_flow.py
  ds_job_flow/ds_job_flow.py
  ds_docs/ds_docs.py
  ldm_convert/ldm_convert.py
  dbm_convert/dbm_convert.py
  msl_convert/msl_convert.py
  msl_lineage/msl_lineage.py
  msl_lineage/lineage_template.html  # HTML-template, ingeladen door msl_lineage.py
```

## Hoe converters worden aangeroepen (web_ui.py)

`web_ui.py` laadt converters dynamisch via `importlib.util.spec_from_file_location()` en roept `mod.main()` aan. Converters worden NIET via `import` of `sys.path` geladen — elke converter wordt als los script uitgevoerd.

Elke converter verwacht:
- Inputbestand in `INPUT_DIR` (`input/`)
- Schrijft output naar `OUTPUT_DIR` (`output/`)
- Heeft een `main()` functie zonder argumenten

## Bestandstype-detectie (web_ui.py)

`detect_type()` bepaalt het bestandstype aan de hand van bestandsextensie of XML-inhoud:

| Signaal | Bestandstype |
|---|---|
| Extensie `.msl` | `msl` |
| `<DSExport` in eerste 4096 bytes | `dsexport` |
| `logicalModelElement` in eerste 4096 bytes | `ldm` |
| `<database` in eerste 4096 bytes | `dbm` |

## Converter-registry (converters.py)

De registry is gecentraliseerd in `converters.py` en bevat per converter:
- `name` — interne sleutel
- `script` — pad naar het `.py`-bestand (`None` = tab-only)
- `menu_label` — label in het CLI-menu (`None` = niet in menu)
- `file_type` — koppeling aan het gedetecteerde bestandstype
- `tab_label` — tabblad-label in de web UI
- `output_suffix` — suffix van het outputbestand

Tab-only entries (bijv. `ldm_datamodel`, `dbm_datamodel`) hebben `script=None`: het bijbehorende hoofdscript genereert dit bestand, de entry zorgt puur voor het tabblad in de UI.

Nieuwe converter toevoegen: één entry in `converters.py` (REGISTRY). `main.py` en `web_ui.py` lezen de registry automatisch.

## Bekende valkuilen

**Namespace package conflict**
`ROOT_DIR` staat in `sys.path` (toegevoegd door `web_ui.py`). Hierdoor kan Python de submap `msl_convert/` importeren als namespace package i.p.v. `msl_convert/msl_convert.py`. Workaround in `msl_lineage.py` en `ds_flow.py`: laden via `importlib.util.spec_from_file_location()` + `exec_module()`.

**sys.argv en logging zijn globale state**
`web_ui.py` muteert `sys.argv` en `logging.root.handlers` tijdelijk tijdens conversie. Werkt correct zolang de server single-threaded is (`HTTPServer`, niet `ThreadingHTTPServer`).

**HTML-templates zijn losse bestanden**
Pas `web_ui_template.html` of `msl_lineage/lineage_template.html` aan voor UI-wijzigingen. De server laadt `web_ui_template.html` eenmalig bij opstart — herstart nodig na wijziging. `lineage_template.html` wordt per conversie ingeladen.

**Placeholders in lineage_template.html**
De template gebruikt `.replace()` (niet `.format()`): `{title}`, `{sources_json}`, `{targets_json}`, `{meta_json}`. Gewone `{` en `}` in de HTML/JS hoeven niet ge-escaped te worden.

**ERD-templates in ldm_convert en dbm_convert**
Beide converters bevatten een inline ERD-template als Python raw string (`ERD_TEMPLATE = r"""..."""`). Alle `{` en `}` in de HTML/JS zijn ge-escaped als `{{` en `}}`, zodat `.format()` ze niet verstoort.

## ERD-layoutsysteem (ldm_convert)

`compute_layout()` detecteert automatisch stermodellen (naam eindigt op `_FT` of ≥4 FK-referenties) en kiest de bijpassende layout. `_hierarchical_layout()` is de fallback voor niet-stermodellen.

Het ERD bevat een **Layout-keuze** in de toolbar (Ster / Hiërarchisch / Grid). Python berekent de eerste twee en stuurt ze als JSON mee (`positions_star_json`, `positions_hier_json`). Grid wordt ter plekke in JS berekend. Wisselen verloopt met een CSS-transitie; posities worden per layout opgeslagen in localStorage (`BASE_KEY + '_' + layout`).

Bij stermodellen verschijnt ook een **Ster-dropdown**. JS detecteert feitentabellen (naam eindigt op `_FT` of `fkOutCount >= STAR_THRESHOLD=4`) en bouwt een `starMap` (ft_id → Set van parent-ids). Bij selectie worden niet-gerelateerde entiteiten verborgen (`display:none`) en hun SVG-lijnen weggelaten. Layout-wisseling wist het filter.

## ds_flow — job flow per sequencer-node

`ds_flow.py` importeert `ds_job_flow` via `importlib` (zelfde patroon als `ds_convert`). Voor elke parallel job die in de sequencer voorkomt roept het `generate_job_flow_html()` aan:
- Serialiseert het Job ET-element naar XML-string via `ET.tostring()`
- Roept `dsj.parse_job(xml_str)` + `dsj.build_html()` aan
- Schrijft het resultaat naar `output/{xml_stem}_{jobname}_JobFlow.html`
- Geeft de bestandsnaam terug als `job_flow_file` in het node-dict

In de modal wordt een `<iframe>` getoond met die bestandsnaam als src. Relatieve URL werkt omdat de Flow HTML zelf ook onder `/output/` wordt geserveerd.

Bij mislukking (`SystemExit` of andere exception) logt `generate_job_flow_html()` een waarschuwing en geeft `None` terug — de "Bekijk job flow"-knop verschijnt dan niet.


## ds_docs — gesplitste documentatie per job (ZIP voor LLM/chatbot)

`ds_docs.py` laadt `ds_convert` via `importlib` (zelfde patroon als `ds_flow`). Per job roept het de render-functies aan uit `ds_convert`:
- `render_sequencer_job()` / `render_parallel_job()` / `render_container()`
- Schrijft elk resultaat als losse entry in een ZIP via `zipfile.ZipFile` (standaardbibliotheek)
- Voegt `index.md` toe met een tabel van alle jobs + uitvoeringsvolgorde per sequencer
- Schrijft ook `{xml_stem}_Docs.html` als landing page zodat de web_ui een "Docs"-tab kan tonen

Output: `output/{xml_stem}_docs.zip` (flat, geen subdirectory in ZIP).

## XMLProperties — OracleConnectorPX

`get_xmlprops_tree()` in `ds_convert.py` controleert eerst een directe `<Property Name="XMLProperties">` van het Record element (formaat bij OracleConnectorPX), en valt daarna terug op de SubRecord-structuur (oudere CustomStage format). Eerder werd alleen SubRecord gecheckt, wat de "XMLProperties konden niet worden geparsed" melding veroorzaakte.

## Open verbeterpunten

Zie `to_do.md` voor de volledige lijst. Belangrijkste open punten:
- Globale state-mutatie `logging.root.handlers` in `web_ui.py` (niet thread-safe)
- DataStage Linter (`ds_linter`) nog te implementeren

## Distributie-ZIP — verplichte bestanden

`build_zip.py` bouwt de ZIP voor eindgebruikers. De volgende bestanden zijn **verplicht** in de ZIP:

- **`README.md`** — de `? Help`-knop in de web UI serveert dit bestand via de `/readme`-route. Zonder dit bestand geeft de Help-knop een 404-fout bij de eindgebruiker.

Voeg nooit bestanden toe aan de ZIP die alleen voor ontwikkelaars bedoeld zijn (`to_do.md`, `.gitignore`, testbestanden, logbestanden, de `temp/`-map). De `ROOT_FILES`-lijst in `build_zip.py` is de gezaghebbende lijst van wat er in de ZIP terechtkomt.

## UI-conventies (web_ui_template.html)

- **Geen emoji's als iconen.** Gebruik inline SVG (Lucide-stijl: `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`, `stroke-linecap="round"`, `stroke-linejoin="round"`). Emoji's zijn platformafhankelijk, niet stijlbaar en ontoegankelijk.
- **Font stack.** Gebruik `system-ui, -apple-system, "Segoe UI", Arial, sans-serif` — geen externe fontdownloads (UWV-netwerk heeft beperkte internettoegang).
- **Kleurcontrasten.** Tekst op de blauwe header (`#005b9a`) minimaal `rgba(255,255,255,.65)` voor klein/decoratief, `.85` voor leesbare statustekst.
- **Drop zone.** Hover-state via `box-shadow: 0 0 0 4px rgba(0,91,154,.08)` (geen outline, geen border-width-animatie).

## Tijdelijke werkbestanden (`temp/`)

Instructiedocumenten voor externe AI-modellen (bijv. Gemini-prompts, taakbeschrijvingen) en terugkoppeling daarvan worden opgeslagen in de tijdelijke werkmap van het project. In dit project is dat `temp/`.

- Instructies naar AG/Gemini: `<tempdir>/<naam>_instructie.md`
- Terugkoppeling / output van AG: `<tempdir>/<naam>_output.md`
- De map staat in `.gitignore` en wordt nooit meegenomen in git
- De naam van de map kan per project verschillen (`temp/`, `TEMP/`, `tmp/`, e.d.) — controleer `.gitignore` of vraag de gebruiker als het niet duidelijk is
