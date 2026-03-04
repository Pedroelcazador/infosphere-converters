"""
converters.py — centrale converter-registry voor Infosphere Converters

Geïmporteerd door zowel web_ui.py als main.py zodat elke nieuwe converter
op precies één plek hoeft te worden toegevoegd.

Velden per converter:
  name          : interne sleutel (ook module-naam bij importlib-laden)
  script        : absoluut pad naar het Python-script  (None = tab-only)
  menu_label    : label in het CLI-menu (main.py)       (None = niet in menu)
  file_type     : 'dsexport', 'ldm' of 'msl'
  tab_label     : tabblad-label in de web GUI
  output_suffix : suffix van het HTML-outputbestand voor de web GUI
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

REGISTRY = [
    {
        'name':          'ds_convert',
        'script':        ROOT_DIR / 'ds_convert'  / 'ds_convert.py',
        'menu_label':    'DataStage → Documentatie (Markdown + HTML)',
        'file_type':     'dsexport',
        'tab_label':     'Documentatie',
        'output_suffix': '_DataStage.html',
    },
    {
        'name':          'ds_flow',
        'script':        ROOT_DIR / 'ds_flow'     / 'ds_flow.py',
        'menu_label':    'DataStage → Sequencer flowdiagram (HTML)',
        'file_type':     'dsexport',
        'tab_label':     'Flow',
        'output_suffix': '_Flow.html',
    },
    {
        'name':          'ds_job_flow',
        'script':        ROOT_DIR / 'ds_job_flow' / 'ds_job_flow.py',
        'menu_label':    'DataStage → Job dataflow diagram (HTML)',
        'file_type':     'dsexport',
        'tab_label':     'Job Flow',
        'output_suffix': '_JobFlow.html',
    },
    {
        'name':          'ldm_convert',
        'script':        ROOT_DIR / 'ldm_convert' / 'ldm_convert.py',
        'menu_label':    'LDM → Datamodel (Markdown + HTML + ERD)',
        'file_type':     'ldm',
        'tab_label':     'ERD',
        'output_suffix': '_ERD.html',
    },
    {
        'name':          'ldm_datamodel',
        'script':        None,   # tab-only: ldm_convert produceert dit bestand ook
        'menu_label':    None,   # niet in CLI-menu
        'file_type':     'ldm',
        'tab_label':     'Datamodel',
        'output_suffix': '_Datamodel.html',
    },
    {
        'name':          'msl_convert',
        'script':        ROOT_DIR / 'msl_convert' / 'msl_convert.py',
        'menu_label':    'MSL → Attribuutmapping (Markdown + HTML)',
        'file_type':     'msl',
        'tab_label':     'Mapping',
        'output_suffix': '_Mapping.html',
    },
    {
        'name':          'msl_lineage',
        'script':        ROOT_DIR / 'msl_lineage' / 'msl_lineage.py',
        'menu_label':    'MSL → Lineage diagram (HTML)',
        'file_type':     'msl',
        'tab_label':     'Lineage',
        'output_suffix': '_Lineage.html',
    },
]
