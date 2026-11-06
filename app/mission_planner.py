"""Deterministic task-aware proposals; never receives observer state or history."""
from battle_planner import INACTIVE, graph, hop_distances, route, execution_feedback


def plans(obs):
    task = obs['own_mission']
    side = obs['perspective']
    own = sorted((u for u in obs['entities'] if u['side'] == side and u['status'] not in INACTIVE), key=lambda u: u['id'])
    foes = [u for u in obs['entities'] if u['side'] != side and u['status'] not in INACTIVE]
    if not own:
        return []
    targets = task['targets']
    variants = []
    if task['kind'] == 'hold':
        variants = [('hold_line', '保持坚守点与后方支援', None), ('hold_screen', '坚守并前出观察', None)]
    elif task['kind'] == 'breakthrough':
        for site in targets:
            variants += [(f'rush_{site["id"]}', f'集中向 {site["id"]} 出口突破', site),
                         (f'covered_{site["id"]}', f'掩护主力向 {site["id"]} 出口脱离', site)]
        if len(task['possible_sites']) > len(targets) and len(own) >= 3:
            variants.append(('diversion', '小股佯动、主力驶向真实出口', targets[0]))
    else:
        variants.append(('guard_balanced', '分区阻击，保留两侧警戒', None))
        for site in targets:
            variants += [(f'guard_{site["id"]}', f'集中阻击 {site["id"]} 通道', site),
                         (f'probe_{site["id"]}', f'保持阻击并观察 {site["id"]} 接近路', site)]
    variants.append(('withdraw', '向任务指定后方整顿', None))
    occupied = {e['current_node'] for e in foes}
    eligible = set(task.get('eligible_units', []))
    results = []
    for pid, title, focus in variants:
        assignments, orders, risks = [], [], []
        for idx, u in enumerate(own):
            start = u['current_node']
            goal, action, note = start, 'DEFEND', '保持阵地'
            urgent = u.get('morale', 100) < 32 or u.get('ammo', 1) == 0
            if pid == 'withdraw' or urgent:
                options = [(n, route(obs, start, n, u['role'], True)[1]) for n in task.get('fallback_nodes', []) if n not in occupied]
                options = [(n, d) for n, d in options if d is not None]
                if options:
                    goal = min(options, key=lambda p: p[1])[0]
                    action, note = 'RETREAT', '沿己方指定退路脱离并整顿'
                else:
                    risks.append(f'{u["id"]}退路受阻，原地防御')
            elif task['kind'] == 'hold':
                goal = task['hold_node']
                action, note = 'MOVE', '守住任务点，等待撤离窗口'
                if pid == 'hold_screen' and u['role'] == 'light' and idx != 0:
                    neighbors = [n for n, _ in graph(obs)[goal] if n not in occupied]
                    if neighbors:
                        goal = min(neighbors, key=lambda n: route(obs, start, n, u['role'])[1] or 0)
                        note = '在坚守点附近观察，保持主力在点上'
            elif task['kind'] == 'breakthrough':
                goal = focus['node']
                action, note = 'MOVE', '任务部队优先抵达指定出口'
                if pid.startswith('covered') and u['id'] not in eligible and foes:
                    goal = min(foes, key=lambda e: hop_distances(obs, start).get(e['current_node'], 999))['current_node']
                    action, note = 'ATTACK', '牵制已知威胁，掩护任务部队'
                if pid == 'diversion' and u['id'] == next((v['id'] for v in own if v['role'] == 'light'), -1):
                    decoys = [s for s in task['possible_sites'] if s['id'] != focus['id']]
                    if decoys:
                        path, _ = route(obs, start, decoys[0]['node'], u['role'])
                        goal = path[max(0, len(path) // 2 - 1)] if path else start
                        note = '向备用通道短程佯动；此单位不计作本轮脱离主力'
            else:
                site = focus or targets[idx % len(targets)]
                goal = site['node']
                action, note = 'MOVE', f'占据 {site["id"]} 出口，阻断穿越'
                if pid.startswith('probe') and u['role'] == 'light':
                    approaches = [n for n, _ in graph(obs)[goal] if n not in occupied]
                    if approaches:
                        # Only own current position and public graph determine this probe.
                        goal = min(approaches, key=lambda n: route(obs, start, n, u['role'])[1] or 0)
                        note = '观察出口接近路；发现或未发现都需按可见范围解释'
            if u['role'] == 'artillery' and not urgent and pid != 'withdraw':
                hd = hop_distances(obs, goal)
                positions = [n['id'] for n in obs['nodes'] if 2 <= hd.get(n['id'], 999) <= 3 and n['id'] not in occupied and all(hop_distances(obs, e['current_node']).get(n['id'], 999) >= 2 for e in foes)]
                if positions:
                    goal = min(positions, key=lambda n: route(obs, start, n, u['role'])[1] or 0)
                    action, note = 'MOVE', '在任务通道后方建立炮火支援阵地'
                else:
                    goal, action, note = start, 'DEFEND', '保护炮兵，等待观察条件'
            path, eta = route(obs, start, goal, u['role'], action == 'RETREAT')
            if eta is None:
                goal, action, path, eta = start, 'DEFEND', [], 0
                risks.append(f'{u["id"]}路线不可达')
            if goal == start:
                action = 'DEFEND'
            # Planner estimates exclude suppression, edge progress, battle delays and routs.
            feasible = eta <= task['remaining_ticks']
            if u['id'] in eligible and task['kind'] == 'breakthrough' and not feasible:
                risks.append(f'{u["id"]}静态路程估计已超出剩余时间')
            orders.append(dict(side=side, unit_id=u['id'], action=action, target_node=goal))
            assignments.append(dict(unit_id=u['id'], role=u['role'], task=note, action=action, target_node=goal,
                                    route=path, estimated_ticks=eta, within_deadline_estimate=feasible))
        if task['kind'] == 'deny' and focus:
            risks.append('集中一侧会削弱另一侧；目标判断仍可能错误')
        results.append(dict(id=pid, title=title, sector=focus['id'] if focus else 'balanced', orders=orders,
                            assignments=assignments, risks=list(dict.fromkeys(risks))))
    return results


def feedback(obs, previous):
    out = execution_feedback(obs, previous)
    task = obs['own_mission']
    out['mission_now'] = {k: task.get(k) for k in ('kind', 'remaining_ticks', 'completed', 'required', 'status')}
    old = (previous or {}).get('mission_at_issue', {})
    out['mission_changed'] = bool(old and any(old.get(k) != task.get(k) for k in ('kind', 'completed', 'status')))
    for unit in out['units']:
        if any(u['id'] == unit['unit_id'] and u['status'] == 'EXITED' for u in obs['entities']):
            unit['result'] = '已按任务脱离战场'
    return out


def scripted_decision(obs):
    candidates = plans(obs)
    task = obs['own_mission']
    preferred = 'hold_line' if task['kind'] == 'hold' else 'guard_balanced' if task['kind'] == 'deny' else 'rush_' + task['targets'][0]['id']
    chosen = next((p for p in candidates if p['id'] == preferred), None)
    return dict(agent_version='mission_rules_v5', controller='scripted', source_tick=obs['tick'],
                selected_plan=chosen['id'] if chosen else None, plan=chosen['title'] if chosen else '无可控部队，等待整顿',
                orders=chosen['orders'] if chosen else [], assignments=chosen['assignments'] if chosen else [],
                candidate_plans=candidates, intent=[], goal_hypotheses=[], evidence=[], grounding_passed=True,
                choice_origin='deterministic_rule_baseline', proposal_origin='deterministic_mission_planner',
                mission_at_issue=task, reconsider_when='任务阶段、进度或接敌变化', seconds=0)
