# CLAUDE.md — Projectcontext Infosphere Converters

Toolkit voor het omzetten van IBM InfoSphere DataStage- en IBM Data Architect-exportbestanden naar interactieve HTML en Markdown. Ontwikkeld voor het DIM-team bij UWV. Uitsluitend Python standaardbibliotheek, geen externe packages.

Ondersteunde bestandstypen: DSExport XML (DataStage), LDM XML (logisch datamodel), DBM XML (fysiek datamodel), MSL (attribuutmapping).

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

## Open verbeterpunten

Zie `to_do.md` voor de volledige lijst. Belangrijkste open punten:
- Globale state-mutatie `logging.root.handlers` in `web_ui.py` (niet thread-safe)
- Stage-rendering duplicatie in `ds_convert.py`
- DataStage Linter (`ds_linter`) nog te implementeren
