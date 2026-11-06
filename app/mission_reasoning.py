"""Task-directed, side-private temporal retrieval. Derived features aren't facts."""
from collections import Counter
from battle_memory import tokens
from battle_planner import hop_distances
import math


def augment_context(obs, context, memory, previous=None):
    task, tick, side = obs['own_mission'], obs['tick'], obs['perspective']
    # Past beliefs are proposals to revisit. Never store them as observations.
    permitted = context['mode'] in ('memory', 'full') and previous and previous.get('source_tick', tick) <= tick and previous.get('side',side)==side
    beliefs = previous.get('goal_hypotheses', []) if permitted else []
    sites = task['possible_sites']
    goal_nodes = [s['node'] for s in sites]
    if task.get('hold_node'):
        goal_nodes.append(task['hold_node'])
    query = dict(as_of_tick=tick, side=side, task=task['kind'], remaining_ticks=task['remaining_ticks'],
                 focus_nodes=goal_nodes, focus_units=[t['unit_id'] for t in context['tracks']],
                 hypotheses_to_check=[dict(objective=b.get('objective'), purpose=b.get('purpose')) for b in beliefs],
                 requested=['last_sighting', 'movement_toward_and_away', 'lost_contact', 'refuting_observations'])
    if context['mode'] == 'memory':
        words = '敌军 移动 脱离视野 ' + ' '.join(map(str, goal_nodes + query['focus_units']))
        qt, near = tokens(words), set()
        for node in goal_nodes:
            near.update(n for n, d in hop_distances(obs, node).items() if d <= 2)
        with memory.lock:
            rows = memory.db.execute('SELECT id,tick,kind,unit,node,text FROM events WHERE side=? AND tick<? ORDER BY tick DESC LIMIT 1200', (side, tick)).fetchall()
        ranked = []
        for eid, when, kind, uid, node, text in rows:
            if '敌军' not in text:
                continue
            ts = tokens(text)
            lexical = sum(min(n, ts[t]) for t, n in qt.items()) / math.sqrt(1 + sum(ts.values()))
            score = lexical + 4 * (node in near) + 3 * (kind in ('movement', 'lost_contact')) + 2 / (1 + (tick - when) / 12)
            ranked.append(dict(id=f'M{eid:05d}', tick=when, kind=kind, unit_id=uid, node=node, text=text, score=round(score, 3)))
        ranked.sort(key=lambda e: (-e['score'], -e['tick'], e['id']))
        chosen, counts = [], Counter()
        for e in ranked:
            key = (e['unit_id'], e['kind'])
            if counts[key] >= 2:
                continue
            chosen.append(e)
            counts[key] += 1
            if len(chosen) == 12:
                break
        # Sighting records plus at most twelve diverse task-retrieved events.
        context['evidence'] = [e for e in context['evidence'] if e['kind'] == 'sighting'] + sorted(chosen, key=lambda e: (e['tick'], e['id']))
    features = []
    for track in context['tracks']:
        positions = track['positions']
        if len(positions) < 2:
            continue
        a, b = positions[-2:]
        for site in sites:
            hd = hop_distances(obs, site['node'])
            delta = hd.get(a['node'], 999) - hd.get(b['node'], 999)
            features.append(dict(kind='derived_hop_change', unit_id=track['unit_id'], objective=site['id'],
                                 interval=[a['tick'], b['tick']], toward_hops=delta, age=track['age'],
                                 sources=[f'F{a["tick"]}U{track["unit_id"]}', f'F{b["tick"]}U{track["unit_id"]}'],
                                 interpretation='图上距离变化；接近出口也可能是侦察或佯动，不能据此确认目标'))
    clues=[]
    for site in sites:
        relevant=[f for f in features if f['objective']==site['id']]
        approach=[f for f in relevant if f['toward_hops']>0]
        away=[f for f in relevant if f['toward_hops']<0]
        clues.append(dict(objective=site['id'],node=site['node'],
                          approaching_observed_units=[f['unit_id'] for f in approach],
                          moving_away_observed_units=[f['unit_id'] for f in away],
                          direction_support=list(dict.fromkeys(s for f in approach for s in f['sources'])),
                          direction_counter=list(dict.fromkeys(s for f in away for s in f['sources'])),
                          caution='由公开图和历史目击计算，不能确认敌方目的或当前坐标'))
    context.update(version='mission_memory_v5', query=query, derived_features=features, corridor_clues=clues, prior_beliefs=beliefs,
                   retrieval_budget=dict(event_limit=12, positions_per_track=4, evidence_count=len(context['evidence']),
                                         history_frames=len(context.get('recent', [])), history_char_limit=42000))
    return context
