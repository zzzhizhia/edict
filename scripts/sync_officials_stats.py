#!/usr/bin/env python3
"""同步各官员统计数据 → data/officials_stats.json

数据源（优先级）：
1. Backend UsageTracker (data/usage_log.jsonl) — Agent SDK 精确记录
2. Claude Code sessions.json — 降级/历史兼容
"""
import json, pathlib, datetime, logging
from file_lock import atomic_json_write

log = logging.getLogger('officials')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / 'data'
USAGE_LOG = DATA / 'usage_log.jsonl'
AGENTS_ROOT = pathlib.Path.home() / '.claude' / 'projects'
CLAUDE_SETTINGS = pathlib.Path.home() / '.claude' / 'settings.json'

# Anthropic 定价（每1M token，美元）
MODEL_PRICING = {
    'anthropic/claude-sonnet-4-6':  {'in':3.0, 'out':15.0, 'cr':0.30, 'cw':3.75},
    'anthropic/claude-opus-4-5':    {'in':15.0,'out':75.0, 'cr':1.50, 'cw':18.75},
    'anthropic/claude-haiku-3-5':   {'in':0.8, 'out':4.0,  'cr':0.08, 'cw':1.0},
    'openai/gpt-4o':                {'in':2.5, 'out':10.0, 'cr':1.25, 'cw':0},
    'openai/gpt-4o-mini':           {'in':0.15,'out':0.6,  'cr':0.075,'cw':0},
    'google/gemini-2.0-flash':      {'in':0.075,'out':0.3, 'cr':0,    'cw':0},
    'google/gemini-2.5-pro':        {'in':1.25,'out':10.0, 'cr':0,    'cw':0},
}

OFFICIALS = [
    {'id':'taizi',   'label':'太子',  'role':'太子',    'emoji':'🤴','rank':'储君'},
    {'id':'zhongshu','label':'中书省','role':'中书令',  'emoji':'📜','rank':'正一品'},
    {'id':'menxia',  'label':'门下省','role':'侍中',    'emoji':'🔍','rank':'正一品'},
    {'id':'shangshu','label':'尚书省','role':'尚书令',  'emoji':'📮','rank':'正一品'},
    {'id':'libu',    'label':'礼部',  'role':'礼部尚书','emoji':'📝','rank':'正二品'},
    {'id':'hubu',    'label':'户部',  'role':'户部尚书','emoji':'💰','rank':'正二品'},
    {'id':'bingbu',  'label':'兵部',  'role':'兵部尚书','emoji':'⚔️','rank':'正二品'},
    {'id':'xingbu',  'label':'刑部',  'role':'刑部尚书','emoji':'⚖️','rank':'正二品'},
    {'id':'gongbu',  'label':'工部',  'role':'工部尚书','emoji':'🔧','rank':'正二品'},
    {'id':'libu_hr', 'label':'吏部',  'role':'吏部尚书','emoji':'👔','rank':'正二品'},
    {'id':'zaochao', 'label':'钦天监','role':'朝报官',  'emoji':'📰','rank':'正三品'},
]

def rj(p, d):
    try: return json.loads(pathlib.Path(p).read_text())
    except Exception: return d


# Pre-load claude settings once (avoid re-reading per agent)
_CLAUDE_CACHE = None

def _load_claude_settings():
    global _CLAUDE_CACHE
    if _CLAUDE_CACHE is None:
        _CLAUDE_CACHE = rj(CLAUDE_SETTINGS, {})
    return _CLAUDE_CACHE


def normalize_model(model_value, fallback='anthropic/claude-sonnet-4-6'):
    if isinstance(model_value, str) and model_value:
        return model_value
    if isinstance(model_value, dict):
        return model_value.get('primary') or model_value.get('id') or fallback
    return fallback

def get_model(agent_id):
    cfg = _load_claude_settings()
    default = normalize_model(cfg.get('agents',{}).get('defaults',{}).get('model',{}), 'anthropic/claude-sonnet-4-6')
    for a in cfg.get('agents',{}).get('list',[]):
        if a.get('id') == agent_id:
            return normalize_model(a.get('model', default), default)
    # 兼容历史：太子曾使用 main 作为运行时 id
    if agent_id == 'taizi':
        for a in cfg.get('agents',{}).get('list',[]):
            if a.get('id') == 'main':
                return normalize_model(a.get('model', default), default)
    return default

def _load_usage_index():
    """读取 usage_log.jsonl 一次，按 agent_id 构建索引。"""
    index = {}
    try:
        text = USAGE_LOG.read_text(errors='ignore')
    except Exception:
        return index
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except Exception:
            continue
        aid = entry.get('agent_id', '')
        if aid not in index:
            index[aid] = {'tin': 0, 'tout': 0, 'cr': 0, 'cw': 0, 'cost': 0.0, 'count': 0, 'last_ts': None}
        rec = index[aid]
        rec['tin'] += entry.get('input_tokens', 0) or 0
        rec['tout'] += entry.get('output_tokens', 0) or 0
        rec['cr'] += entry.get('cache_read_tokens', 0) or 0
        rec['cw'] += entry.get('cache_write_tokens', 0) or 0
        rec['cost'] += entry.get('cost_usd', 0) or 0
        rec['count'] += 1
        ts_str = entry.get('timestamp')
        if ts_str:
            try:
                t = datetime.datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                if rec['last_ts'] is None or t > rec['last_ts']:
                    rec['last_ts'] = t
            except Exception:
                pass
    return index


def scan_agent_from_usage_log(agent_id, usage_index):
    """从预加载的 usage_index 中提取指定 agent 的统计数据。"""
    rec = usage_index.get(agent_id)
    if not rec or rec['count'] == 0:
        return None
    return {
        'tokens_in': rec['tin'], 'tokens_out': rec['tout'],
        'cache_read': rec['cr'], 'cache_write': rec['cw'],
        'sessions': rec['count'],
        'last_active': rec['last_ts'].strftime('%Y-%m-%d %H:%M') if rec['last_ts'] else None,
        'messages': rec['count'],
        'cost_usd_precise': round(rec['cost'], 4),
    }


def scan_agent(agent_id):
    """从 sessions.json 读取 token 统计（累计所有 session）— 降级数据源"""
    sj = AGENTS_ROOT / agent_id / 'sessions' / 'sessions.json'
    if not sj.exists() and agent_id == 'taizi':
        sj = AGENTS_ROOT / 'main' / 'sessions' / 'sessions.json'
    if not sj.exists():
        return {'tokens_in':0,'tokens_out':0,'cache_read':0,'cache_write':0,'sessions':0,'last_active':None,'messages':0}
    
    data = rj(sj, {})
    tin = tout = cr = cw = 0
    last_ts = None
    
    for sid, v in data.items():
        tin += v.get('inputTokens', 0) or 0
        tout += v.get('outputTokens', 0) or 0
        cr  += v.get('cacheRead', 0) or 0
        cw  += v.get('cacheWrite', 0) or 0
        ts = v.get('updatedAt')
        if ts:
            try:
                t = datetime.datetime.fromtimestamp(ts/1000) if isinstance(ts,int) else datetime.datetime.fromisoformat(ts.replace('Z','+00:00'))
                if last_ts is None or t > last_ts: last_ts = t
            except Exception: pass
    
    # Estimate message count from most recent session JSONL
    msg_count = 0
    if data:
        try:
            sf_key = max(data.keys(), key=lambda k: data[k].get('updatedAt',0) or 0, default=None)
        except Exception:
            sf_key = None
    else:
        sf_key = None
    if sf_key and data[sf_key].get('sessionFile'):
        sf = AGENTS_ROOT / agent_id / 'sessions' / pathlib.Path(data[sf_key]['sessionFile']).name
        try:
            lines = sf.read_text(errors='ignore').splitlines()
            for ln in lines:
                try:
                    e = json.loads(ln)
                    if e.get('type') == 'message' and e.get('message',{}).get('role') == 'assistant':
                        msg_count += 1
                except Exception: pass
        except Exception: pass

    return {
        'tokens_in': tin, 'tokens_out': tout,
        'cache_read': cr, 'cache_write': cw,
        'sessions': len(data),
        'last_active': last_ts.strftime('%Y-%m-%d %H:%M') if last_ts else None,
        'messages': msg_count,
    }

def calc_cost(s, model):
    p = MODEL_PRICING.get(model, MODEL_PRICING['anthropic/claude-sonnet-4-6'])
    usd = (s['tokens_in']/1e6*p['in'] + s['tokens_out']/1e6*p['out']
         + s['cache_read']/1e6*p['cr'] + s['cache_write']/1e6*p['cw'])
    return round(usd, 4)

def get_task_stats(org_label, tasks):
    done   = [t for t in tasks if t.get('state')=='Done' and t.get('org')==org_label]
    active = [t for t in tasks if t.get('state') in ('Doing','Review','Assigned') and t.get('org')==org_label]
    fl = sum(1 for t in tasks for f in t.get('flow_log',[])
             if f.get('from')==org_label or f.get('to')==org_label)
    # 参与的旨意（JJC）列表
    participated = []
    for t in tasks:
        if not t['id'].startswith('JJC'): continue
        for f in t.get('flow_log',[]):
            if f.get('from')==org_label or f.get('to')==org_label:
                if t['id'] not in [x['id'] for x in participated]:
                    participated.append({'id':t['id'],'title':t.get('title',''),'state':t.get('state','')})
                break
    return {'tasks_done':len(done),'tasks_active':len(active),
            'flow_participations':fl,'participated_edicts':participated}

def get_hb(agent_id, live_tasks):
    for t in live_tasks:
        if t.get('sourceMeta',{}).get('agentId')==agent_id and t.get('heartbeat'):
            return t['heartbeat']
    return {'status':'idle','label':'⚪ 待命','ageSec':None}

def main():
    tasks = rj(DATA/'tasks_source.json', [])
    live  = rj(DATA/'live_status.json', {})
    live_tasks = live.get('tasks', [])

    usage_index = _load_usage_index()
    result = []
    for off in OFFICIALS:
        model   = get_model(off['id'])
        # Prefer precise data from UsageTracker, fallback to session scanning
        ss_precise = scan_agent_from_usage_log(off['id'], usage_index)
        ss_legacy  = scan_agent(off['id'])
        ss = ss_precise if ss_precise else ss_legacy
        ts      = get_task_stats(off['label'], tasks)
        hb      = get_hb(off['id'], live_tasks)
        # Use precise cost if available, otherwise estimate from token counts
        cost_usd = ss.get('cost_usd_precise') or calc_cost(ss, model)

        result.append({
            **off,
            'model': model,
            'model_short': model.split('/')[-1] if isinstance(model, str) and '/' in model else str(model),
            'sessions': ss['sessions'],
            'tokens_in': ss['tokens_in'],
            'tokens_out': ss['tokens_out'],
            'cache_read': ss['cache_read'],
            'cache_write': ss['cache_write'],
            'tokens_total': ss['tokens_in'] + ss['tokens_out'],
            'messages': ss['messages'],
            'cost_usd': cost_usd,
            'cost_cny': round(cost_usd * 7.25, 2),
            'last_active': ss['last_active'],
            'heartbeat': hb,
            'tasks_done': ts['tasks_done'],
            'tasks_active': ts['tasks_active'],
            'flow_participations': ts['flow_participations'],
            'participated_edicts': ts['participated_edicts'],
            'merit_score': ts['tasks_done']*10 + ts['flow_participations']*2 + min(ss['sessions'],20),
        })

    result.sort(key=lambda x: x['merit_score'], reverse=True)
    for i, r in enumerate(result): r['merit_rank'] = i+1

    totals = {
        'tokens_total': sum(r['tokens_total'] for r in result),
        'cache_total':  sum(r['cache_read']+r['cache_write'] for r in result),
        'cost_usd':     round(sum(r['cost_usd'] for r in result), 2),
        'cost_cny':     round(sum(r['cost_cny'] for r in result), 2),
        'tasks_done':   sum(r['tasks_done'] for r in result),
    }
    top = max(result, key=lambda x: x['merit_score'], default={})

    payload = {
        'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'officials': result,
        'totals': totals,
        'top_official': top.get('label',''),
    }
    atomic_json_write(DATA/'officials_stats.json', payload)
    log.info(f'{len(result)} officials | cost=¥{totals["cost_cny"]} | top={top.get("label","")}')

if __name__ == '__main__':
    main()
