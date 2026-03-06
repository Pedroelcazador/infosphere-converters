#!/usr/bin/env python3
"""
tests/test_converters.py — smoke-tests voor de Infosphere Converters

Principes:
  - Elk converter-script wordt geladen via importlib.util.spec_from_file_location
    + exec_module, consistent met het laadpatroon in web_ui.py.
  - INPUT_DIR en OUTPUT_DIR worden ná het laden overschreven naar tijdelijke mappen.
  - Minimale maar geldige XML/MSL-invoerbestanden worden aangemaakt in de tempdir.
  - Smoke-tests roepen main() aan en controleren of de verwachte output bestaat.
  - Eenheidstests controleren pure functies zonder I/O.

Uitvoeren:
  python -m pytest tests/          (vanuit de projectroot)
  python -m unittest tests/test_converters.py
"""

import importlib.util
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Minimale testfixtures
# ---------------------------------------------------------------------------

# Geldige DSExport XML voor ds_convert en ds_flow (attributen op DSExport-tag)
MINIMAL_DSEXPORT = """\
<?xml version="1.0" encoding="UTF-8"?>
<DSExport ServerName="TestServer" Date="2026-01-01">
<Job Identifier="TestParJob" JobType="1" DateModified="2026-01-01">
  <Record Identifier="DSJobDefRecord" Type="DSJobDef">
    <Property Name="JobDescription">Testomschrijving</Property>
  </Record>
</Job>
</DSExport>
"""

# DSExport met CDATA in Description (test dat ET CDATA transparant afhandelt)
MINIMAL_DSEXPORT_CDATA = """\
<?xml version="1.0" encoding="UTF-8"?>
<DSExport ServerName="TestServer" Date="2026-01-01">
<Job Identifier="TestCdataJob" JobType="1" DateModified="2026-01-01">
  <Record Identifier="ROOT" Type="DSJobDef">
    <Property Name="Name">TestCdataJob</Property>
    <Property Name="Description"><![CDATA[Beschrijving met <speciale> tekens & meer]]></Property>
  </Record>
</Job>
</DSExport>
"""

# DSExport met HTML-entities in Description (test dat ET entities decodeert)
MINIMAL_DSEXPORT_ENTITIES = """\
<?xml version="1.0" encoding="UTF-8"?>
<DSExport Date="2026-01-01">
<Job Identifier="TestEntityJob" JobType="1" DateModified="2026-01-01">
  <Record Identifier="ROOT" Type="DSJobDef">
    <Property Name="Name">TestEntityJob</Property>
    <Property Name="Description">Verwerkt input &amp; output data</Property>
  </Record>
</Job>
</DSExport>
"""

# Geldige DSExport voor ds_job_flow:
#   - vereist exacte string "<DSExport>" (zonder attributen)
#   - vereist een ROOT record (job-metadata) en V0 record (ContainerView met stages)
MINIMAL_DSEXPORT_JOBFLOW = """\
<?xml version="1.0" encoding="UTF-8"?>
<DSExport>
<Job Identifier="TestParJob" JobType="1" DateModified="2026-01-01">
  <Record Identifier="ROOT" Type="DSJobDef">
    <Property Name="Name">TestParJob</Property>
    <Property Name="Description">Test parallelle job</Property>
  </Record>
  <Record Identifier="V0" Type="ContainerView">
    <Property Name="StageList">S1</Property>
    <Property Name="StageNames">TestStage</Property>
    <Property Name="StageTypeIDs">OracleConnectorPX</Property>
    <Property Name="LinkNames"></Property>
    <Property Name="TargetStageIDs"></Property>
    <Property Name="LinkSourcePinIDs"></Property>
    <Property Name="StageXPos">100</Property>
    <Property Name="StageYPos">100</Property>
    <Property Name="StageXSize">96</Property>
    <Property Name="StageYSize">48</Property>
  </Record>
</Job>
</DSExport>
"""

# Geldige DBM XML voor dbm_convert
MINIMAL_DBM = """\
<?xml version="1.0" encoding="UTF-8"?>
<database name="TestDB">
  <databaseElement type="Schema" name="DBO">
    <databaseElement type="Table" name="TEST_TABLE" id="t1">
      <properties>
        <property name="Description" value="Testtabel"/>
      </properties>
      <databaseElement type="Column" name="ID" id="c1">
        <properties>
          <property name="Data Type" value="NUMBER(10)"/>
          <property name="Is Primary Key" value="true"/>
          <property name="Is Nullable" value="false"/>
        </properties>
      </databaseElement>
      <databaseElement type="Column" name="NAAM" id="c2">
        <properties>
          <property name="Data Type" value="VARCHAR2(100)"/>
          <property name="Is Nullable" value="true"/>
        </properties>
      </databaseElement>
    </databaseElement>
  </databaseElement>
</database>
"""

# DSExport met sequencer-job voor ds_flow sequencer-pad
MINIMAL_DSEXPORT_SEQUENCER = """\
<?xml version="1.0" encoding="UTF-8"?>
<DSExport ServerName="TestServer" Date="2026-01-01">
<Job Identifier="par_job1" JobType="1" DateModified="2026-01-01">
  <Record Identifier="ROOT" Type="DSJobDef">
    <Property Name="Name">par_job1</Property>
  </Record>
</Job>
<Job Identifier="seq_main" JobType="2" DateModified="2026-01-01">
  <Record Identifier="ROOT" Type="DSJobDef">
    <Property Name="Name">seq_main</Property>
  </Record>
  <Record Identifier="ACT1" Type="JSJobActivity">
    <Property Name="Name">RunJob1</Property>
    <Property Name="Jobname">par_job1</Property>
    <Property Name="OutputPins">ACT1P1</Property>
    <Property Name="InputPins"></Property>
  </Record>
  <Record Identifier="ACT1P1" Type="JSActivityOutput">
    <Property Name="Partner">ACT2</Property>
    <Property Name="ConditionType">2</Property>
    <Property Name="Name">OK</Property>
  </Record>
  <Record Identifier="ACT2" Type="JSTerminatorActivity">
    <Property Name="Name">End</Property>
    <Property Name="OutputPins"></Property>
    <Property Name="InputPins">ACT2P1</Property>
  </Record>
</Job>
</DSExport>
"""

# Geldige LDM XML voor ldm_convert
MINIMAL_LDM = """\
<?xml version="1.0" encoding="UTF-8"?>
<logicalModelElement type="LogicalModel" name="TestModel">
  <modelElement type="Model Information">
    <modelProperty name="name" value="TestModel"/>
  </modelElement>
  <logicalModelElement type="Entity" name="TestEntity">
    <modelProperty name="description" value="Testentiteit"/>
    <logicalModelElement type="Attribute" name="ID">
      <modelElement type="LogicalDomain">
        <modelProperty name="logicalDataType" value="Integer"/>
      </modelElement>
    </logicalModelElement>
  </logicalModelElement>
</logicalModelElement>
"""

# Geldige MSL XML voor msl_convert en msl_lineage
_MSL_NS = "http:///com/ibm/datatools/metadata/mapping/model/model.ecore"
MINIMAL_MSL = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<msl:mappingRoot xmlns:msl="{_MSL_NS}" name="TestMapping">
  <msl:inputs  name="resource0" location="/schema/source.ldm"/>
  <msl:outputs name="resource1" location="/schema/target.ldm"/>
  <msl:mapping name="MAP_TARGET_TABLE">
    <msl:input  path="$resource0/SOURCE_TABLE"/>
    <msl:output path="$resource1/TARGET_TABLE"/>
    <msl:mapping name="MAP_COL1">
      <msl:input  path="$resource0/SOURCE_TABLE/COL1"/>
      <msl:output path="$resource1/TARGET_TABLE/COL1"/>
    </msl:mapping>
  </msl:mapping>
</msl:mappingRoot>
"""


# ---------------------------------------------------------------------------
# Module-loader — zelfde patroon als web_ui.py
# ---------------------------------------------------------------------------

def _load_module(script_path: Path, module_name: str):
    """
    Laad een Python-script als module via importlib.

    Cruciale stap: spec.loader.exec_module(module) MOET worden aangeroepen
    na module_from_spec(). Zonder exec_module is het module-object leeg —
    alle functies en module-variabelen ontbreken.

    Consistent met web_ui.py:
        spec = importlib.util.spec_from_file_location(conv_name, sp)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
    """
    sys.modules.pop(module_name, None)
    spec   = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# ds_convert
# ---------------------------------------------------------------------------

class TestDsConvert(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td = tempfile.TemporaryDirectory()
        td       = Path(self._td.name)
        self.inp = td / 'input'
        self.out = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_export.xml').write_text(MINIMAL_DSEXPORT, encoding='utf-8')
        self.mod = _load_module(ROOT / 'ds_convert' / 'ds_convert.py', 'ds_convert')
        self.mod.INPUT_DIR  = self.inp
        self.mod.OUTPUT_DIR = self.out

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    # --- smoke test ---

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft precies één *_DataStage.html."""
        self.mod.main()
        html_files = list(self.out.glob('*_DataStage.html'))
        self.assertEqual(len(html_files), 1,
                         f"Verwacht één *_DataStage.html, gevonden: {[f.name for f in html_files]}")
        self.assertGreater(html_files[0].stat().st_size, 0)

    # --- make_anchor ---

    def test_make_anchor_spaces(self):
        self.assertEqual(self.mod.make_anchor('Mijn Job'), 'mijn-job')

    def test_make_anchor_underscores(self):
        self.assertEqual(self.mod.make_anchor('Hello_World'), 'hello-world')

    def test_make_anchor_strips_special_chars(self):
        self.assertEqual(self.mod.make_anchor('a b+c!'), 'a-bc')

    # --- prop ---

    def test_prop_found(self):
        # prop() werkt nu op ET-elementen; wrapper-element als parent
        elem = ET.fromstring('<Record><Property Name="JobDescription">TestBeschrijving</Property></Record>')
        self.assertEqual(self.mod.prop(elem, 'JobDescription'), 'TestBeschrijving')

    def test_prop_missing_returns_empty(self):
        elem = ET.fromstring('<Record><Property Name="Other">Waarde</Property></Record>')
        self.assertEqual(self.mod.prop(elem, 'Ontbreekt'), '')

    def test_prop_cdata(self):
        """prop() extraheert CDATA-inhoud correct — ET handelt dit transparant af."""
        elem = ET.fromstring(
            '<Record><Property Name="Desc"><![CDATA[inhoud & meer]]></Property></Record>'
        )
        self.assertEqual(self.mod.prop(elem, 'Desc'), 'inhoud & meer')

    def test_prop_html_entity(self):
        """prop() decodeert XML-entities correct via ET."""
        elem = ET.fromstring(
            '<Record><Property Name="Desc">input &amp; output</Property></Record>'
        )
        self.assertEqual(self.mod.prop(elem, 'Desc'), 'input & output')

    # --- split_jobs ---

    def test_split_jobs_count(self):
        root = ET.fromstring(MINIMAL_DSEXPORT)
        jobs = self.mod.split_jobs(root)
        self.assertEqual(len(jobs), 1)

    def test_split_jobs_fields(self):
        root = ET.fromstring(MINIMAL_DSEXPORT)
        job_id, job_type, _ = self.mod.split_jobs(root)[0]
        self.assertEqual(job_id,   'TestParJob')
        self.assertEqual(job_type, '1')

    # --- validate_dse ---

    def test_validate_dse_rejects_non_dse(self):
        root = ET.fromstring('<SomeOtherRoot/>')
        with self.assertRaises(SystemExit):
            self.mod.validate_dse(root, Path('test.xml'))

    def test_validate_dse_rejects_no_jobs(self):
        root = ET.fromstring('<DSExport><Header/></DSExport>')
        with self.assertRaises(SystemExit):
            self.mod.validate_dse(root, Path('test.xml'))

    def test_validate_dse_accepts_valid(self):
        root = ET.fromstring(MINIMAL_DSEXPORT)
        try:
            self.mod.validate_dse(root, Path('test.xml'))
        except SystemExit:
            self.fail("validate_dse() riep sys.exit() aan voor een geldige DSExport")

    # --- get_xmlprops_tree ---

    def test_get_xmlprops_tree_nested_in_collection(self):
        """Regressietest: XMLProperties genest in Collection/SubRecord wordt gevonden."""
        xml_props = "&lt;Properties version='1.1'&gt;&lt;Common/&gt;&lt;/Properties&gt;"
        elem = ET.fromstring(f"""
            <Record Type="CustomStage">
              <Property Name="StageType">OracleConnectorPX</Property>
              <Collection Name="Properties" Type="CustomProperty">
                <SubRecord>
                  <Property Name="Name">XMLProperties</Property>
                  <Property Name="Value">{xml_props}</Property>
                </SubRecord>
              </Collection>
            </Record>
        """)
        result = self.mod.get_xmlprops_tree(elem)
        self.assertIsNotNone(result, "get_xmlprops_tree() moet de geneste XMLProperties vinden")

    def test_get_xmlprops_tree_returns_none_when_absent(self):
        """get_xmlprops_tree() geeft None terug als XMLProperties ontbreekt."""
        elem = ET.fromstring('<Record Type="CustomStage"><Property Name="Name">X</Property></Record>')
        self.assertIsNone(self.mod.get_xmlprops_tree(elem))

    # --- CDATA & entities smoke tests ---

    def test_smoke_main_cdata(self):
        """main() verwerkt CDATA in descriptions correct en plaatst inhoud in output."""
        (self.inp / 'test_export.xml').unlink()
        (self.inp / 'test_cdata.xml').write_text(MINIMAL_DSEXPORT_CDATA, encoding='utf-8')
        self.mod.main()
        html_files = list(self.out.glob('*_DataStage.html'))
        self.assertEqual(len(html_files), 1)
        content = html_files[0].read_text(encoding='utf-8')
        self.assertIn('speciale', content)

    def test_smoke_main_entities(self):
        """main() decodeert HTML-entities in descriptions correct."""
        (self.inp / 'test_export.xml').unlink()
        (self.inp / 'test_entities.xml').write_text(MINIMAL_DSEXPORT_ENTITIES, encoding='utf-8')
        self.mod.main()
        html_files = list(self.out.glob('*_DataStage.html'))
        self.assertEqual(len(html_files), 1)
        content = html_files[0].read_text(encoding='utf-8')
        self.assertIn('input &amp; output', content)


# ---------------------------------------------------------------------------
# ds_flow
# ---------------------------------------------------------------------------

class TestDsFlow(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td = tempfile.TemporaryDirectory()
        td       = Path(self._td.name)
        self.inp = td / 'input'
        self.out = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_export.xml').write_text(MINIMAL_DSEXPORT, encoding='utf-8')
        # ds_flow importeert ds_convert als 'ds' op moduleniveau (top-level import).
        # Na het laden overschrijven we INPUT_DIR op het ds_convert-module-object
        # dat ds_flow gebruikt (self.mod.ds). find_xml_file() leest INPUT_DIR
        # uit zijn __globals__, die IS de ds_convert module namespace.
        self.mod = _load_module(ROOT / 'ds_flow' / 'ds_flow.py', 'ds_flow')
        self.mod.ds.INPUT_DIR = self.inp
        self.mod.OUTPUT_DIR   = self.out

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft precies één *_Flow.html."""
        self.mod.main()
        html_files = list(self.out.glob('*_Flow.html'))
        self.assertEqual(len(html_files), 1,
                         f"Verwacht één *_Flow.html, gevonden: {[f.name for f in html_files]}")
        self.assertGreater(html_files[0].stat().st_size, 0)

    def test_parse_all_returns_list(self):
        result = self.mod.parse_all(MINIMAL_DSEXPORT)
        self.assertIsInstance(result, list)

    def test_parse_all_no_sequencer_diagrams(self):
        # MINIMAL_DSEXPORT heeft JobType="1" (parallel job), geen sequencer (JobType="2").
        # parse_all geeft geen sequencer-flow-diagrammen terug; de parallel job
        # verschijnt hooguit als activiteitsnode in een overzichtsitem.
        result = self.mod.parse_all(MINIMAL_DSEXPORT)
        # Geen item mag de parallel job-id als root-diagram-id hebben
        flow_ids = [item['id'] for item in result]
        self.assertNotIn('TestParJob', flow_ids)

    def test_smoke_main_sequencer(self):
        """main() verwerkt een sequencer-export en schrijft een *_Flow.html."""
        (self.inp / 'test_export.xml').unlink()
        (self.inp / 'seq_export.xml').write_text(MINIMAL_DSEXPORT_SEQUENCER, encoding='utf-8')
        self.mod.ds.INPUT_DIR = self.inp
        self.mod.main()
        html_files = list(self.out.glob('*_Flow.html'))
        self.assertEqual(len(html_files), 1,
                         f"Verwacht één *_Flow.html, gevonden: {[f.name for f in html_files]}")
        self.assertGreater(html_files[0].stat().st_size, 0)

    def test_parse_all_sequencer_has_nodes(self):
        """parse_all() detecteert sequencer-job en retourneert nodes."""
        result = self.mod.parse_all(MINIMAL_DSEXPORT_SEQUENCER)
        seq_ids = [item['id'] for item in result]
        self.assertIn('seq_main', seq_ids)
        seq = next(item for item in result if item['id'] == 'seq_main')
        self.assertGreater(len(seq['nodes']), 0)

    def test_parse_all_sequencer_has_links(self):
        """parse_all() detecteert de OK-link in de sequencer."""
        result = self.mod.parse_all(MINIMAL_DSEXPORT_SEQUENCER)
        seq = next(item for item in result if item['id'] == 'seq_main')
        self.assertGreater(len(seq['links']), 0)


# ---------------------------------------------------------------------------
# ds_job_flow
# ---------------------------------------------------------------------------

class TestDsJobFlow(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td  = tempfile.TemporaryDirectory()
        td        = Path(self._td.name)
        self.root = td
        self.inp  = td / 'input'
        self.out  = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_jobflow.xml').write_text(MINIMAL_DSEXPORT_JOBFLOW, encoding='utf-8')
        # ds_job_flow gebruikt ROOT_DIR / 'input' (geen aparte INPUT_DIR module-variabele).
        # ROOT_DIR overschrijven zodat ROOT_DIR / 'input' naar de tempmap wijst.
        self.mod = _load_module(ROOT / 'ds_job_flow' / 'ds_job_flow.py', 'ds_job_flow')
        self.mod.ROOT_DIR   = self.root
        self.mod.OUTPUT_DIR = self.out

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft precies één *_JobFlow.html."""
        self.mod.main()
        html_files = list(self.out.glob('*_JobFlow.html'))
        self.assertEqual(len(html_files), 1,
                         f"Verwacht één *_JobFlow.html, gevonden: {[f.name for f in html_files]}")
        self.assertGreater(html_files[0].stat().st_size, 0)

    def test_stage_type_label_known(self):
        label = self.mod.stage_type_label('OracleConnectorPX')
        self.assertEqual(label, 'Oracle Connector')

    def test_stage_type_label_unknown_returns_raw(self):
        label = self.mod.stage_type_label('OnbekendeStage')
        self.assertEqual(label, 'OnbekendeStage')

    def test_prop_found(self):
        xml = '<Property Name="Name">TestJob</Property>'
        self.assertEqual(self.mod.prop(xml, 'Name'), 'TestJob')

    def test_parse_ds_list_returns_list(self):
        # parse_ds_list gebruikt \(N)-codering; lege string → lege lijst
        result = self.mod.parse_ds_list('')
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# ldm_convert
# ---------------------------------------------------------------------------

class TestLdmConvert(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td = tempfile.TemporaryDirectory()
        td       = Path(self._td.name)
        self.inp = td / 'input'
        self.out = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_model.xml').write_text(MINIMAL_LDM, encoding='utf-8')
        self.mod = _load_module(ROOT / 'ldm_convert' / 'ldm_convert.py', 'ldm_convert')
        self.mod.INPUT_DIR  = self.inp
        self.mod.OUTPUT_DIR = self.out

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft minstens één HTML-output."""
        self.mod.main()
        html_files = list(self.out.glob('*.html'))
        self.assertGreater(len(html_files), 0,
                           "Verwacht minstens één .html in output/")

    def test_make_anchor(self):
        self.assertEqual(self.mod.make_anchor('Test Entity'), 'test-entity')

    def test_is_dim_meta_prefix_true(self):
        self.assertTrue(self.mod.is_dim_meta('DIM Start Datum Geldigheid'))

    def test_is_dim_meta_exact_true(self):
        self.assertTrue(self.mod.is_dim_meta('Commit Time'))

    def test_is_dim_meta_false(self):
        self.assertFalse(self.mod.is_dim_meta('KLANTNUMMER'))

    def test_validate_ldm_rejects_wrong_root(self):
        root = ET.fromstring('<DSExport/>')
        with self.assertRaises(SystemExit):
            self.mod.validate_ldm(root, Path('test.xml'))

    def test_validate_ldm_rejects_no_entities(self):
        root = ET.fromstring('<logicalModelElement type="LogicalModel" name="X"/>')
        with self.assertRaises(SystemExit):
            self.mod.validate_ldm(root, Path('test.xml'))

    def test_validate_ldm_accepts_valid(self):
        root = ET.fromstring(MINIMAL_LDM)
        try:
            self.mod.validate_ldm(root, Path('test.xml'))
        except SystemExit:
            self.fail("validate_ldm() riep sys.exit() aan voor een geldig LDM")


# ---------------------------------------------------------------------------
# msl_convert
# ---------------------------------------------------------------------------

class TestMslConvert(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td = tempfile.TemporaryDirectory()
        td       = Path(self._td.name)
        self.inp = td / 'input'
        self.out = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_mapping.msl').write_text(MINIMAL_MSL, encoding='utf-8')
        self.mod = _load_module(ROOT / 'msl_convert' / 'msl_convert.py', 'msl_convert')
        self.mod.INPUT_DIR  = self.inp
        self.mod.OUTPUT_DIR = self.out

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft precies één *_Mapping.html."""
        self.mod.main()
        html_files = list(self.out.glob('*_Mapping.html'))
        self.assertEqual(len(html_files), 1,
                         f"Verwacht één *_Mapping.html, gevonden: {[f.name for f in html_files]}")
        self.assertGreater(html_files[0].stat().st_size, 0)

    def test_make_anchor(self):
        self.assertEqual(self.mod.make_anchor('Mijn Tabel'), 'mijn-tabel')

    def test_strip_path_three_parts(self):
        self.assertEqual(
            self.mod.strip_path('$resource0/BRON_TABEL/KOLOM1'),
            ('$resource0', 'BRON_TABEL', 'KOLOM1'),
        )

    def test_strip_path_two_parts(self):
        self.assertEqual(
            self.mod.strip_path('$resource0/BRON_TABEL'),
            ('$resource0', 'BRON_TABEL', ''),
        )

    def test_classify_direct(self):
        self.assertEqual(self.mod.classify_mapping([('$r0', 'T', 'c1')], False), 'direct')

    def test_classify_constant(self):
        self.assertEqual(self.mod.classify_mapping([], True), 'constant')

    def test_classify_concat(self):
        inputs = [('$r0', 'T', 'c1'), ('$r0', 'T', 'c2')]
        self.assertEqual(self.mod.classify_mapping(inputs, False), 'concat')

    def test_classify_join(self):
        inputs = [('$r0', 'T1', 'c1'), ('$r0', 'T2', 'c1')]
        self.assertEqual(self.mod.classify_mapping(inputs, False), 'join')

    def test_classify_lookup(self):
        inputs = [('$r0', 'T1', 'c1'), ('$r0', 'T2', 'c2')]
        self.assertEqual(self.mod.classify_mapping(inputs, False), 'lookup')

    def test_parse_msl_structure(self):
        root = ET.fromstring(MINIMAL_MSL)
        data = self.mod.parse_msl(root)
        self.assertIn('target_mappings', data)
        self.assertIn('all_sources',     data)

    def test_parse_msl_one_target(self):
        root = ET.fromstring(MINIMAL_MSL)
        data = self.mod.parse_msl(root)
        self.assertEqual(len(data['target_mappings']), 1)
        self.assertEqual(data['target_mappings'][0]['target_table'], 'TARGET_TABLE')

    def test_parse_msl_source_present(self):
        root = ET.fromstring(MINIMAL_MSL)
        data = self.mod.parse_msl(root)
        self.assertIn('SOURCE_TABLE', data['all_sources'])

    def test_validate_msl_rejects_wrong_root(self):
        root = ET.fromstring('<wrongRoot/>')
        with self.assertRaises(SystemExit):
            self.mod.validate_msl(root, Path('test.msl'))

    def test_validate_msl_accepts_valid(self):
        root = ET.fromstring(MINIMAL_MSL)
        try:
            self.mod.validate_msl(root, Path('test.msl'))
        except SystemExit:
            self.fail("validate_msl() riep sys.exit() aan voor een geldige MSL")


# ---------------------------------------------------------------------------
# msl_lineage
# ---------------------------------------------------------------------------

class TestMslLineage(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td = tempfile.TemporaryDirectory()
        td       = Path(self._td.name)
        self.inp = td / 'input'
        self.out = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_mapping.msl').write_text(MINIMAL_MSL, encoding='utf-8')
        # msl_lineage importeert find_msl_file vanuit msl_convert op moduleniveau
        # via `from msl_convert import find_msl_file, ...`.
        # find_msl_file.__globals__ IS msl_convert.__dict__, dus INPUT_DIR instellen
        # via sys.modules['msl_convert'] bereikt de geïmporteerde functie correct.
        self.mod = _load_module(ROOT / 'msl_lineage' / 'msl_lineage.py', 'msl_lineage')
        self.mod.OUTPUT_DIR = self.out
        sys.modules['msl_convert'].INPUT_DIR = self.inp

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft precies één *_Lineage.html."""
        self.mod.main()
        html_files = list(self.out.glob('*_Lineage.html'))
        self.assertEqual(len(html_files), 1,
                         f"Verwacht één *_Lineage.html, gevonden: {[f.name for f in html_files]}")
        self.assertGreater(html_files[0].stat().st_size, 0)

    def test_build_lineage_data_structure(self):
        """build_lineage_data() retourneert de verwachte sleutels."""
        # Laad msl_convert los (als hulpmodule) om parse_msl te gebruiken
        msl_mod = _load_module(ROOT / 'msl_convert' / 'msl_convert.py', '_msl_convert_util')
        root    = ET.fromstring(MINIMAL_MSL)
        data    = msl_mod.parse_msl(root)
        result  = self.mod.build_lineage_data(data)
        self.assertIn('sources', result)
        self.assertIn('targets', result)
        self.assertIsInstance(result['sources'], list)
        self.assertIsInstance(result['targets'], list)

    def test_build_lineage_data_source_present(self):
        """build_lineage_data() bevat SOURCE_TABLE als bron."""
        msl_mod = _load_module(ROOT / 'msl_convert' / 'msl_convert.py', '_msl_convert_util')
        root    = ET.fromstring(MINIMAL_MSL)
        data    = msl_mod.parse_msl(root)
        result  = self.mod.build_lineage_data(data)
        source_ids = [s['id'] for s in result['sources']]
        self.assertIn('SOURCE_TABLE', source_ids)

    def test_build_lineage_data_target_present(self):
        """build_lineage_data() bevat TARGET_TABLE als doel."""
        msl_mod = _load_module(ROOT / 'msl_convert' / 'msl_convert.py', '_msl_convert_util')
        root    = ET.fromstring(MINIMAL_MSL)
        data    = msl_mod.parse_msl(root)
        result  = self.mod.build_lineage_data(data)
        target_ids = [t['id'] for t in result['targets']]
        self.assertIn('TARGET_TABLE', target_ids)


# ---------------------------------------------------------------------------
# dbm_convert
# ---------------------------------------------------------------------------

class TestDbmConvert(unittest.TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._td = tempfile.TemporaryDirectory()
        td       = Path(self._td.name)
        self.inp = td / 'input'
        self.out = td / 'output'
        self.inp.mkdir()
        self.out.mkdir()
        (self.inp / 'test_model.xml').write_text(MINIMAL_DBM, encoding='utf-8')
        self.mod = _load_module(ROOT / 'dbm_convert' / 'dbm_convert.py', 'dbm_convert')
        self.mod.INPUT_DIR  = self.inp
        self.mod.OUTPUT_DIR = self.out

    def tearDown(self):
        logging.disable(logging.NOTSET)
        self._td.cleanup()

    def test_smoke_main(self):
        """main() loopt foutloos en schrijft _Datamodel.html en _ERD.html."""
        self.mod.main()
        html_files = list(self.out.glob('*.html'))
        names = [f.name for f in html_files]
        self.assertTrue(any('Datamodel' in n for n in names),
                        f"Geen *_Datamodel.html gevonden in: {names}")
        self.assertTrue(any('ERD' in n for n in names),
                        f"Geen *_ERD.html gevonden in: {names}")

    def test_validate_dbm_rejects_wrong_root(self):
        root = ET.fromstring('<DSExport/>')
        with self.assertRaises(SystemExit):
            self.mod.validate_dbm(root, Path('test.xml'))

    def test_validate_dbm_rejects_no_schemas(self):
        root = ET.fromstring('<database name="X"/>')
        with self.assertRaises(SystemExit):
            self.mod.validate_dbm(root, Path('test.xml'))

    def test_validate_dbm_accepts_valid(self):
        root = ET.fromstring(MINIMAL_DBM)
        try:
            self.mod.validate_dbm(root, Path('test.xml'))
        except SystemExit:
            self.fail("validate_dbm() riep sys.exit() aan voor een geldige DBM")

    def test_parse_model_structure(self):
        root   = ET.fromstring(MINIMAL_DBM)
        model  = self.mod.parse_model(root)
        self.assertIn('tables',     model)
        self.assertIn('stats',      model)
        self.assertIn('model_name', model)

    def test_parse_model_one_table(self):
        root  = ET.fromstring(MINIMAL_DBM)
        model = self.mod.parse_model(root)
        self.assertEqual(len(model['tables']), 1)
        self.assertEqual(model['tables'][0]['name'], 'TEST_TABLE')

    def test_parse_model_columns(self):
        root  = ET.fromstring(MINIMAL_DBM)
        model = self.mod.parse_model(root)
        cols  = model['tables'][0]['columns']
        self.assertEqual(len(cols), 2)

    def test_parse_model_pk_detected(self):
        root  = ET.fromstring(MINIMAL_DBM)
        model = self.mod.parse_model(root)
        pk_cols = [c for c in model['tables'][0]['columns'] if c['pk']]
        self.assertEqual(len(pk_cols), 1)
        self.assertEqual(pk_cols[0]['name'], 'ID')

    def test_parse_model_nullable(self):
        root  = ET.fromstring(MINIMAL_DBM)
        model = self.mod.parse_model(root)
        cols  = {c['name']: c for c in model['tables'][0]['columns']}
        self.assertFalse(cols['ID']['nullable'])
        self.assertTrue(cols['NAAM']['nullable'])

    def test_make_anchor(self):
        self.assertEqual(self.mod.make_anchor('Test Tabel'), 'test-tabel')


if __name__ == '__main__':
    unittest.main(verbosity=2)
