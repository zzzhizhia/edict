#!/usr/bin/env python3
"""应用 data/pending_model_changes.json → claude code agent 配置"""
import json, pathlib, datetime, shutil, logging, glob
from file_lock import atomic_json_write, atomic_json_read

log = logging.getLogger('model_change')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

BASE = pathlib.Path(__file__).parent.parent
DATA = BASE / 'data'
CLAUDE_SETTINGS = pathlib.Path.home() / '.claude' / 'settings.json'
PENDING = DATA / 'pending_model_changes.json'
CHANGE_LOG = DATA / 'model_change_log.json'
MAX_BACKUPS = 10


def rj(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def cleanup_backups():
    """只保留最近 MAX_BACKUPS 个备份"""
    pattern = str(CLAUDE_SETTINGS.parent / 'settings.json.bak.model-*')
    baks = sorted(glob.glob(pattern))
    for old in baks[:-MAX_BACKUPS]:
        try:
            pathlib.Path(old).unlink()
        except OSError:
            pass


def main():
    if not PENDING.exists():
        return
    pending = rj(PENDING, [])
    if not pending:
        return

    cfg = rj(CLAUDE_SETTINGS, {})
    agents_list = cfg.get('agents', {}).get('list', [])
    default_model = cfg.get('agents', {}).get('defaults', {}).get('model', {}).get('primary', '')

    applied, errors = [], []
    for change in pending:
        ag_id = change.get('agentId', '').strip()
        new_model = change.get('model', '').strip()
        if not ag_id or not new_model:
            errors.append({'change': change, 'error': 'missing fields'})
            continue
        found = False
        for ag in agents_list:
            if ag.get('id') == ag_id:
                old = ag.get('model', default_model)
                if new_model == default_model:
                    ag.pop('model', None)
                else:
                    ag['model'] = new_model
                applied.append({'at': datetime.datetime.now().isoformat(), 'agentId': ag_id, 'oldModel': old, 'newModel': new_model})
                found = True
                break
        if not found:
            errors.append({'change': change, 'error': f'agent {ag_id} not found'})

    if applied:
        bak = CLAUDE_SETTINGS.parent / f'settings.json.bak.model-{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}'
        shutil.copy2(CLAUDE_SETTINGS, bak)
        cleanup_backups()
        cfg['agents']['list'] = agents_list
        atomic_json_write(CLAUDE_SETTINGS, cfg)

        log_data = rj(CHANGE_LOG, [])
        log_data.extend(applied)
        if len(log_data) > 200:
            log_data = log_data[-200:]
        atomic_json_write(CHANGE_LOG, log_data)

        for e in applied:
            log.info(f'{e["agentId"]}: {e["oldModel"]} → {e["newModel"]}')

        atomic_json_write(PENDING, [])
        atomic_json_write(DATA / 'last_model_change_result.json', {
            'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'applied': applied, 'errors': errors,
        })
    elif errors:
        log.warning(f'{len(errors)} changes failed, 0 applied')
        atomic_json_write(PENDING, [])


if __name__ == '__main__':
    main()
