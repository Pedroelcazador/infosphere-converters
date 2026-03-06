# Infosphere Converters

Toolkit voor het omzetten van IBM InfoSphere DataStage- en IBM Data Architect-exportbestanden naar leesbare documentatie en interactieve HTML-visualisaties.

Ontwikkeld voor het DIM-team bij UWV, gericht op ETL-engineers, informatiearchitecten en testers.

---

## Vereisten

- Python 3.10 of hoger
- Geen externe packages — uitsluitend de Python standaardbibliotheek

---

## Starten

### Windows (aanbevolen)

Dubbelklik op **`start.bat`**. De webinterface opent automatisch in **Microsoft Edge**. Er verschijnt geen terminalvenster.

> **Opmerking:** de software opent altijd Edge, ook als Internet Explorer als standaardbrowser is ingesteld. Edge moet geïnstalleerd zijn op de machine.

### Linux / Crostini

```bash
./start.sh
```

Of zonder uitvoerrechten: `bash start.sh`.

### Handmatig

```bash
python3 web_ui.py
```

De server start op `http://localhost:8080` (of de eerstvolgende vrije poort tot 8099) en opent de browser automatisch. Op Windows wordt altijd Microsoft Edge gebruikt.

---

## Web Interface

De web interface is de aanbevolen manier om de toolkit te gebruiken.

### Een bestand converteren

1. Sleep een inputbestand naar het dropveld, of klik om een bestand te kiezen
2. De conversie start automatisch — afhankelijk van het bestandstype worden de juiste converters uitgevoerd
3. De resultaten verschijnen als tabbladen in het uitvoerpaneel

Ondersteunde bestandstypen:

| Bestand | Herkend als | Tabbladen |
|---|---|---|
| DSExport XML (`<DSExport>`) — losse job | DataStage | Documentatie · Job Flow |
| DSExport XML (`<DSExport>`) — sequence | DataStage | Documentatie · Flow |
| LDM XML (`logicalModelElement`) | Logisch datamodel | ERD · Datamodel |
| DBM XML (`<database>`) | Fysiek datamodel | ERD · Datamodel |
| MSL-bestand (`.msl`) | Attribuutmapping | Mapping · Lineage |

### Knoppen

| Knop | Functie |
|---|---|
| **↗ Nieuw venster** | Opent het actieve tabblad in een apart browservenster |
| **📦 Download zip** | Download alle outputbestanden van de huidige sessie als zip |
| **⬇ Opslaan** | Download het actieve tabblad als losse HTML |
| **🗑 Nieuwe sessie** | Wist de inputmap zodat een nieuw bestand kan worden geüpload |
| **? Help** | Opent deze documentatie in een apart venster |

### Beperkingen

- Upload slechts **één bestand tegelijk**. Bij meerdere bestanden geeft de interface een foutmelding.
- Bij elke nieuwe serverstart wordt de inputmap automatisch leeggemaakt.

---

## De zeven converters

### 1. `ds_convert` — DataStage documentatie

**Input:** IBM DataStage DSExport XML (`.xml`)
**Output:** `<naam>_DataStage.md` + `<naam>_DataStage.html`

Genereert volledige tekstuele documentatie van alle jobs in een DSExport:

- Sequencer-jobs en parallel jobs met beschrijving, parameters en stages
- Oracle Connector details: SQL-queries, tabelinformatie, write mode
- Wijzigingshistorie per job
- SQL-blokken met syntax highlighting

---

### 2. `ds_flow` — Sequencer flowdiagram

> Wordt alleen uitgevoerd bij een DSExport met een sequencer-job.

**Input:** IBM DataStage DSExport XML
**Output:** `<naam>_Flow.html`

Interactief flowdiagram per sequencer-job:

- OK (groen) / NOK (rood) / onvoorwaardelijk (gestippeld) paden
- Klik op een job-activiteit voor SQL en tabeldetails van de bijbehorende parallel job
- Topologische ranking van nodes

---

### 3. `ds_job_flow` — Job dataflow diagram

> Wordt alleen uitgevoerd bij een DSExport met een losse parallel job (geen sequencer).

**Input:** IBM DataStage DSExport XML
**Output:** `<jobname>_JobFlow.html`

Interactief dataflow-diagram van de interne structuur van een parallel job:

- Stages gepositioneerd op basis van de originele XY-coördinaten uit het XML
- Klik op een stage voor SQL, tabelinformatie en kolomdefinities

---

### 4. `ldm_convert` — Logisch datamodel

**Input:** IBM Data Architect LDM XML (`.xml`)
**Output:** `<naam>_Datamodel.md` + `<naam>_Datamodel.html` + `<naam>_ERD.html`

Documenteert alle entiteiten en attributen uit een logisch datamodel:

- Attribuuttabel met datatype, PK, verplicht, surrogate key en beschrijving
- DIM/bitemporale metadata-velden ingeklapt in een uitklapbare sectie
- Interactief ERD met keuze uit drie layouts: **Ster** (feitentabellen centraal), **Hiërarchisch** (FK-diepte) en **Grid** (alfabetisch raster)
- Foreign key relaties met multipliciteit en crow's foot-notatie

---

### 5. `dbm_convert` — Fysiek datamodel

**Input:** IBM Data Architect DBM XML (`.xml`)
**Output:** `<naam>_Datamodel.md` + `<naam>_Datamodel.html` + `<naam>_ERD.html`

Documenteert alle tabellen en kolommen uit een fysiek datamodel:

- Kolomtabel met datatype, PK, nullable, identity en beschrijving
- Per schema gegroepeerd in de inhoudsopgave
- Interactief ERD met drie weergavemodi (None / Keys / All)
- 🔑 voor primary key-kolommen, ⚙ voor identity-kolommen, ∅ voor nullable kolommen

---

### 6. `msl_convert` — Attribuutmapping

**Input:** IBM Data Architect MSL-bestand (`.msl`)
**Output:** `<naam>_Mapping.md` + `<naam>_Mapping.html`

Converteert een mapping specification naar een leesbare attribuuttabel:

- Mapping-types: direct, concat, join, lookup, constant
- Filtercondicties en join-condities per doeltabel
- Notities per attribuutmapping

---

### 7. `msl_lineage` — Lineage diagram

**Input:** IBM Data Architect MSL-bestand (`.msl`)
**Output:** `<naam>_Lineage.html`

Interactief data-lineage diagram:

- Bronnen links, doeltabellen rechts, verbindingslijnen per attribuutmapping
- Primaire bronnen (direct/concat) en secundaire bronnen (join/lookup) visueel onderscheiden
- Filter op mapping-type via chips in de toolbar
- Klik op een kaart of verbinding voor attribuutdetails in een zijpaneel
- Kaarten zijn versleepbaar voor een aangepaste layout
- **▴ Inklappen** verbergt alle uitgevouwen attribuutpanelen; **↺ Reset** herstelt de beginposities

---

## Mappenstructuur

```
infosphere-converters/
  start.bat            ← Windows startscript (geen terminalvenster)
  start.sh             ← Linux/Crostini startscript
  web_ui.py            ← webinterface, aanbevolen startpunt
  main.py              ← optioneel commandoregelinterface
  md_to_html.py        ← gedeelde module (Markdown → HTML)
  README.md            ← deze documentatie
  input/               ← plaats hier het te converteren bestand
  output/              ← alle gegenereerde bestanden
  ds_convert/
  ds_flow/
  ds_job_flow/
  ldm_convert/
  dbm_convert/
  msl_convert/
  msl_lineage/
```

Logbestanden worden per converter bijgehouden in de bijbehorende submap (bijv. `ds_convert/ds_convert.log`).

---

## Validatie

Elk script valideert het inputbestand voordat de conversie start:

| Situatie | Gedrag |
|---|---|
| Geen bestand in `input/` | Foutmelding + afbreken |
| Meer dan één bestand in `input/` | Foutmelding met bestandsnamen + afbreken |
| Verkeerd bestandstype of root-element | Foutmelding met uitleg + afbreken |

---

## Licentie

MIT
