# CLAUDE.md — Projectcontext Infosphere Converters

Toolkit voor het omzetten van IBM InfoSphere DataStage- en IBM Data Architect-exportbestanden naar interactieve HTML en Markdown. Ontwikkeld voor het DIM-team bij UWV. Uitsluitend Python standaardbibliotheek, geen externe packages.

## Startpunten

- **Windows**: `start.bat` (dubbelklik, geen terminalvenster)
- **Server**: `python3 web_ui.py` → http://localhost:8080
- **CLI**: `python3 main.py`

## Mapstructuur

```
infosphere-converters/
  web_ui.py               # HTTP-server (poort 8080), converter-orchestratie
  web_ui_template.html    # UI-template, ingeladen door web_ui.py bij opstart
  main.py                 # CLI-menu
  md_to_html.py           # Gedeelde module: Markdown → gestylde HTML
  start.bat               # Windows starter (pythonw, geen console)
  input/                  # Één inputbestand tegelijk
  output/                 # Gegenereerde HTML/MD bestanden
  ds_convert/ds_convert.py
  ds_flow/ds_flow.py
  ds_job_flow/ds_job_flow.py
  ldm_convert/ldm_convert.py
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

## Converter-registry (web_ui.py)

Vier dicts bepalen het gedrag bij een upload:

```python
CONVERTERS       # conv_name → pad naar .py bestand
AUTO_RUN         # bestandstype → lijst van conv_names om uit te voeren
TAB_LABELS       # conv_name → tabblad-label in de UI
CONV_OUTPUT_SUFFIX  # conv_name → suffix van het outputbestand
```

`ldm_datamodel` is een tab-only entry (geen eigen script): `ldm_convert` genereert zowel `_ERD.html` als `_Datamodel.html`. De registry-entry zonder CONVERTERS-pad zorgt puur voor het tabblad.

Nieuwe converter toevoegen: aanpassen in alle vier dicts én in `main.py` (MENU).

## Bekende valkuilen

**Namespace package conflict**
`ROOT_DIR` staat in `sys.path` (toegevoegd door `web_ui.py`). Hierdoor kan Python de submap `msl_convert/` importeren als namespace package i.p.v. `msl_convert/msl_convert.py`. Workaround in `msl_lineage.py` en `ds_flow.py`:
```python
sys.modules.pop('msl_convert', None)          # verwijder stale namespace package
sys.path.insert(0, str(ROOT_DIR / 'msl_convert'))
from msl_convert import find_msl_file, ...
```
Dit is functioneel correct maar niet thread-safe. Zie `to_do.md` item #3 voor de structurele oplossing.

**sys.argv en logging zijn globale state**
`web_ui.py` muteert `sys.argv` en `logging.root.handlers` tijdelijk tijdens conversie. Werkt correct zolang de server single-threaded is (`HTTPServer`, niet `ThreadingHTTPServer`).

**HTML-templates zijn losse bestanden**
Pas `web_ui_template.html` of `msl_lineage/lineage_template.html` aan voor UI-wijzigingen. De server laadt `web_ui_template.html` eenmalig bij opstart — herstart nodig na wijziging. `lineage_template.html` wordt per conversie ingeladen.

**Placeholders in lineage_template.html**
De template gebruikt `.replace()` (niet `.format()`): `{title}`, `{sources_json}`, `{targets_json}`, `{meta_json}`. Gewone `{` en `}` in de HTML/JS hoeven niet ge-escaped te worden.

## Open verbeterpunten

Zie `to_do.md` voor de volledige lijst. Belangrijkste open punten:
- `ds_convert.py` gebruikt regex voor XML-parsing (fragiel) in plaats van `ElementTree`
- Converter-registry is gesplitst over `main.py` en `web_ui.py`
- Geen geautomatiseerde tests
