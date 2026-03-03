# Infosphere Converters

Convert IBM InfoSphere DataStage exports and IBM Data Architect LDM/MSL files to readable Markdown documentation and interactive HTML visualizations.

## Achtergrond

IBM InfoSphere exporteert jobs en datamodellen in XML-formaten die niet direct leesbaar zijn voor een breed publiek. Deze toolset zet die exports automatisch om naar:

- **Markdown** — voor snel overzicht en delen met collega's of AI-tools
- **HTML** — interactieve diagrammen en documentatie met sidebar-navigatie, syntax highlighting en klikbare details

De tools zijn ontwikkeld voor het DIM-team bij UWV en zijn gericht op ETL-engineers, informatieanarchitecten en testers.

---

## Vereisten

- Python 3.10 of hoger
- Geen externe packages — alleen de Python standaardbibliotheek

---

## Installatie

```bash
git clone https://github.com/Pedroelcazador/infosphere-converters.git
cd infosphere-converters
```

Klaar. Geen installatiestap nodig.

---

## Gebruik

1. Zet je inputbestand in de `input/` map
2. Start het hoofdmenu:

```bash
python3 main.py
```

3. Kies een conversie uit het menu
4. De output verschijnt in de `output/` map

```
══════════════════════════════════════════════════
  Infosphere Converters
══════════════════════════════════════════════════
  1.  DataStage → Documentatie (Markdown + HTML)
  2.  DataStage → Sequencer flowdiagram (HTML)
  3.  DataStage → Job dataflow diagram (HTML)
  4.  LDM → Datamodel (Markdown + HTML + ERD)
  5.  MSL → Attribuutmapping (Markdown + HTML)
  6.  MSL → Lineage diagram (HTML)
  0.  Afsluiten
──────────────────────────────────────────────────
  📄 Input: mijn_export.xml
──────────────────────────────────────────────────
  Keuze:
```

---

## Mappenstructuur

```
infosphere-converters/
  main.py              ← hoofdmenu, start hier
  md_to_html.py        ← gedeelde module (Markdown → HTML)
  input/               ← zet hier je inputbestand (één tegelijk)
  output/              ← alle gegenereerde bestanden
  ds_convert/
    ds_convert.py
  ds_flow/
    ds_flow.py
  ds_job_flow/
    ds_job_flow.py
  ldm_convert/
    ldm_convert.py
  msl_convert/
    msl_convert.py
  msl_lineage/
    msl_lineage.py
```

Logbestanden worden per script bijgehouden in de scriptmap (bijv. `ds_convert/ds_convert.log`).

---

## De zes converters

### 1. `ds_convert` — DataStage documentatie

**Input:** IBM DataStage DSExport XML (`.xml`, root element `<DSExport>`)  
**Output:** `<naam>_DataStage.md` + `<naam>_DataStage.html`

Genereert volledige tekstuele documentatie van alle jobs in een DSExport:
- Sequencer-jobs en parallel jobs met beschrijving, parameters en stages
- Oracle Connector details: SQL-queries, tabelinformatie, write mode
- Wijzigingshistorie per job
- SQL-blokken met syntax highlighting

---

### 2. `ds_flow` — Sequencer flowdiagram

**Input:** IBM DataStage DSExport XML  
**Output:** `<naam>_Flow.html`

Interactief flowdiagram per sequencer-job:
- OK (groen) / NOK (rood) / onvoorwaardelijk (gestippeld) paden
- Klik op een job-activiteit voor SQL en tabeldetails van de bijbehorende parallel job
- Topologische ranking van nodes

---

### 3. `ds_job_flow` — Job dataflow diagram

**Input:** IBM DataStage DSExport XML  
**Output:** `<jobname>_JobFlow.html`

Interactief dataflow-diagram van de interne structuur van een parallel job:
- Stages gepositioneerd op basis van de originele XY-coördinaten uit het XML
- Klik op een stage voor SQL, tabelinformatie en kolomdefinities

---

### 4. `ldm_convert` — Logisch datamodel

**Input:** IBM Data Architect LDM XML (`.xml`, root element `logicalModelElement`)  
**Output:** `<modelnaam>_Datamodel.md` + `<modelnaam>_Datamodel.html` + `<modelnaam>_ERD.html`

Documenteert alle entiteiten en attributen uit een logisch datamodel:
- Attribuuttabel met datatype, PK, verplicht, surrogate key en beschrijving
- DIM/bitemporale metadata-velden ingeklapt in een uitklapbare sectie
- Interactief ERD met vier weergavemodi (None / Keys / Functional / All)
- Foreign key relaties met multipliciteit

---

### 5. `msl_convert` — Attribuutmapping

**Input:** IBM Data Architect MSL-bestand (`.msl`)  
**Output:** `<naam>_Mapping.md` + `<naam>_Mapping.html`

Converteert een mapping specification naar een leesbare attribuuttabel:
- Mapping-types: direct, concat, join, lookup, constant
- Filtercondicties en join-condities per doeltabel
- Notities per attribuutmapping

---

### 6. `msl_lineage` — Lineage diagram

**Input:** IBM Data Architect MSL-bestand (`.msl`)  
**Output:** `<naam>_Lineage.html`

Interactief data-lineage diagram:
- Bronnen links, doeltabellen rechts, verbindingen per attribuut
- Primaire bronnen (direct/concat) en secundaire bronnen (join/lookup) visueel onderscheiden
- Klik op een verbinding voor attribuutdetails

---

## Validatie

Elk script valideert het inputbestand voordat de conversie start:

| Situatie | Gedrag |
|---|---|
| Geen bestand in `input/` | Foutmelding + exit |
| Meer dan één bestand in `input/` | Foutmelding met bestandsnamen + exit |
| Verkeerd bestandstype of root-element | Foutmelding met uitleg + exit |

---

## Licentie

MIT
