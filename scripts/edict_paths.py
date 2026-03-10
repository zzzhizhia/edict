"""统一路径模块 — 所有脚本通过 EDICT_HOME 环境变量定位 data/ 和 scripts/"""
import os
import pathlib

EDICT_HOME = pathlib.Path(
    os.environ.get('EDICT_HOME', pathlib.Path.home() / '.claude' / 'edict')
)
DATA = EDICT_HOME / 'data'
SCRIPTS = EDICT_HOME / 'scripts'
REPORTS = EDICT_HOME / 'reports'
