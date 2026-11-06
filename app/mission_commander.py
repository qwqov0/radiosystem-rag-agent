"""v5 mission commander: bounded observations -> hypotheses -> joint plan.

Source validation checks provenance/time, not whether an interpretation is true.
"""
import hashlib
import json
from battle_memory import RULES
from mission_planner import plans, feedback

PURPOSES = ['breakthrough', 'deny', 'probe', 'feint', 'withdraw', 'unknown']
TRIGGERS = ['new_contact', 'lost_contact', 'flanked', 'low_morale', 'mission_phase_changed',
            'mission_progress', 'deadline_close', 'plan_blocked', 'periodic']


def decide(obs, memory, mode='memory'):
    context = memory.decision_context(obs, mode)
    return decide_context(obs, context, getattr(memory, 'previous_plan', None))


def decide_context(obs, context, previous=None, infer=None):
    if obs.get('perspective') not in ('red', 'blue') or not obs.get('own_mission'):
        raise ValueError('mission_side_observation_required')
    if infer is None:
        from model_client import chat
        infer = chat
    tick, side, task = obs['tick'], obs['perspective'], obs['own_mission']
    if context['query'].get('as_of_tick') != tick or context['query'].get('side') != side:
        raise ValueError('context_scope_mismatch')
    if any(e['tick'] > tick for e in context['evidence']) or any(t['last_seen_tick'] > tick for t in context['tracks']):
        raise ValueError('future_evidence')
    candidates = plans(obs)
    report = feedback(obs, previous)
    # Keep revised beliefs separate from the source facts and execution feedback.
    revisions = []
    for belief in context.get('prior_beliefs', []):
        new = [f for f in context.get('derived_features', []) if f['objective'] == belief.get('objective') and f['interval'][-1] > (previous or {}).get('source_tick', tick)]
        delta = sum(f['toward_hops'] for f in new)
        revisions.append(dict(previous_objective=belief.get('objective'), previous_purpose=belief.get('purpose'),
                              assessment='新目击方向相容，仍未确认目的' if new and delta > 0 else '新目击远离该处，应重新比较假设' if new and delta < 0 else '尚无足够新证据，保留不确定性',
                              sources=list(dict.fromkeys(s for f in new for s in f['sources']))))
    report['hypothesis_updates'] = revisions
    base = dict(agent_version='commander_v5', controller=context['mode'], source_tick=tick,
                mission_at_issue=task, evidence=context['evidence'], tracks=context['tracks'],
                derived_features=context.get('derived_features', []), prior_beliefs=context.get('prior_beliefs', []),
                corridor_clues=context.get('corridor_clues', []),
                retrieval_query=context['query'], retrieval_budget=context.get('retrieval_budget', {}), feedback=report,
                candidate_plans=candidates, proposal_origin='deterministic_mission_planner', choice_origin='local_llm',
                friendly_at_issue={str(u['id']):dict(hp=u['hp'], morale=u.get('morale', 100), node=u['current_node']) for u in obs['entities'] if u['side'] == side})
    if not candidates:
        return dict(**base, selected_plan=None, orders=[], intent=[], goal_hypotheses=[], plan='无可控部队，等待整顿', grounding_passed=True, seconds=0)
    tracks = {t['unit_id']:t for t in context['tracks']}
    sources = {e['id']:e for e in context['evidence']}
    evidence_ids = [eid for eid, e in sources.items() if e.get('unit_id') in tracks and '敌军' in e['text']]
    known_objectives = [s['id'] for s in task['possible_sites']] + ['unknown']
    objectives = known_objectives if evidence_ids else ['unknown']
    enemy_role = '突破方' if task['kind']=='deny' else '阻击方'
    purposes = [p for p in PURPOSES if p != ('deny' if task['kind']=='deny' else 'breakthrough')] if evidence_ids else ['unknown']
    schema = {'type':'object', 'additionalProperties':False, 'properties':{
        'goal_hypotheses':{'type':'array', 'minItems':2 if evidence_ids and not task['target_public'] else 1, 'maxItems':3 if evidence_ids else 1, 'items':{
            'type':'object', 'additionalProperties':False, 'properties':{
                'objective':{'type':'string', 'enum':objectives}, 'purpose':{'type':'string', 'enum':purposes},
                'confidence':{'type':'string', 'enum':['low','medium'] if evidence_ids else ['low']},
                'support':{'type':'array', 'minItems':1 if evidence_ids else 0, 'maxItems':3 if evidence_ids else 0, 'items':{'type':'string', 'enum':evidence_ids or ['NO_EVIDENCE']}},
                'counter_evidence':{'type':'array', 'maxItems':3 if evidence_ids else 0, 'items':{'type':'string', 'enum':evidence_ids or ['NO_EVIDENCE']}},
                'basis':{'type':'string', 'maxLength':130}, 'would_change_if':{'type':'string', 'maxLength':100}},
            'required':['objective','purpose','confidence','support','counter_evidence','basis','would_change_if']}},
        'selected_plan':{'type':'string', 'enum':[p['id'] for p in candidates]},
        'choice_reason':{'type':'string', 'maxLength':180},
        'information_need':{'type':'string', 'maxLength':100},
        'reconsider_when':{'type':'array', 'minItems':1, 'maxItems':3, 'items':{'type':'string', 'enum':TRIGGERS}}},
        'required':['goal_hypotheses','selected_plan','choice_reason','information_need','reconsider_when']}
    prompt = dict(own_task=task, opponent_public_role=enemy_role,
                  role_reminder='goal_hypotheses描述敌方目的，selected_plan描述我方行动；不能混淆双方。',
                  current=dict(tick=tick, side=side,
                  friendlies=[u for u in obs['entities'] if u['side']==side],
                  visible_enemies=[u for u in obs['entities'] if u['side']!=side], visible_nodes=obs.get('visible_nodes', [])),
                  public_map=obs['nodes'], roads=obs['edges'], temporal_query=context['query'],
                  source_facts=context['evidence'], tracks=context['tracks'],
                  derived_features=context.get('derived_features', []), recent_observations=context.get('recent', []),
                  computed_corridor_clues=context.get('corridor_clues', []),
                  prior_hypotheses_to_recheck=context.get('prior_beliefs', []), execution_feedback=report,
                  proposals=[{k:p[k] for k in ('id','title','assignments','risks')} for p in candidates], rules=RULES,
                  mission_rules='任务成功优先于旧占点计分。EXITED代表按任务脱离，不能再次受令或被重复计数。敌方任务进度未提供时不可推测成事实。公开目标是任务信息，不能算成功猜中敌方意图。',
                  question='比较敌方目的的竞争假设，按当前证据支持强弱排序，结合带时间的己方目击提出反证。computed_corridor_clues是图计算的方向线索：approaching接近，moving_away远离，不等于真实意图。可借方向线索提出某侧低把握突破/试探的待验证假设；不必等确认真实目的后才提出假设。不要为两个方向机械复制相同的依据，接近一侧与远离另一侧应分别讨论。有目击且目标隐藏时至少比较两个不同假设，unknown可以作为竞争项；每项用support引用至少一条实际目击解释判断。不确定时用probe观察最值得核查的接近路。无目击必须目标和目的均unknown，引用为空。不要混淆敌我目的。选择提案并指出何种新事实会改变判断，不以歼灭替代任务。')
    digest = hashlib.sha256(json.dumps(prompt, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    response = infer([dict(role='system', content='你是虚构节点战棋的任务指挥模型。只使用己方可见观察与检索事实，不能读取对手私有任务或全局状态。事实、图计算特征、旧假设严格分开。引用来源只能说明依据存在，不能证明意图正确。证据不足应明确未知，低把握可主动观察。只选择已列出的联合计划。简洁输出JSON。'),
                      dict(role='user', content=json.dumps(prompt, ensure_ascii=False, separators=(',',':')))], max_tokens=1200, schema=schema)
    if response.get('finish_reason') == 'length':
        raise ValueError('truncated_decision')
    data = json.loads(response['text'])
    if data.get('selected_plan') not in [p['id'] for p in candidates]:
        raise ValueError('invalid_plan_choice')
    errors, checks, warnings = [], [], []
    hypotheses = data.get('goal_hypotheses', [])
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 3:
        raise ValueError('invalid_hypothesis_count')
    if evidence_ids and not task['target_public'] and len({(h.get('objective'),h.get('purpose')) for h in hypotheses}) < 2:
        errors.append('missing_competing_hypothesis')
    for h in hypotheses:
        if h.get('objective') not in objectives or h.get('purpose') not in purposes or h.get('confidence') not in ('low','medium'):
            errors.append('invalid_hypothesis')
        support, counter = h.get('support', []), h.get('counter_evidence', [])
        if not isinstance(support, list) or not isinstance(counter, list) or len(support)>3 or len(counter)>3:
            raise ValueError('invalid_citations')
        if h.get('objective') != 'unknown' and not support:
            errors.append('unsupported_goal')
        if evidence_ids and not support:
            errors.append('missing_observation_basis')
        if not evidence_ids and (h.get('objective') != 'unknown' or h.get('purpose') != 'unknown'):
            errors.append('invented_intent_without_observation')
        if h.get('objective') == 'unknown' and h.get('confidence') != 'low':
            errors.append('unknown_must_remain_low')
        for eid in support + counter:
            e = sources.get(eid)
            ok = eid in evidence_ids and bool(e and e['tick'] <= tick)
            checks.append(dict(id=eid, source_time_and_unit_valid=ok))
            if not ok:
                errors.append('unknown_or_unrelated_evidence')
            elif tick-e['tick']>12 and h.get('confidence')=='medium':
                warnings.append('引用陈旧目击；中等把握仍需新观察复核')
        if not h.get('basis') or not h.get('would_change_if'):
            errors.append('missing_hypothesis_reason_or_refutation')
    conditions = data.get('reconsider_when', [])
    if not isinstance(conditions, list) or not conditions or len(conditions)>3 or any(t not in TRIGGERS for t in conditions):
        errors.append('invalid_reconsider_condition')
    chosen = next(p for p in candidates if p['id']==data['selected_plan'])
    intents = [dict(hypothesis=f'{h["objective"]} / {h["purpose"]}', confidence=h['confidence'],
                    evidence=h.get('support', []), counter_evidence=h.get('counter_evidence', []), basis=h.get('basis', '')) for h in hypotheses]
    return dict(**base, selected_plan=chosen['id'], plan=chosen['title'], assignments=chosen['assignments'],
                orders=chosen['orders'] if not errors else [], intent=intents, goal_hypotheses=hypotheses,
                information_need=data.get('information_need', ''), choice_reason=data.get('choice_reason', ''),
                reconsider_when=' / '.join(conditions), trigger_conditions=conditions, grounding_passed=not errors,
                grounding_scope='source_identity_and_time_only; intent_truth_not_verified', grounding_errors=sorted(set(errors)),
                evidence_checks=checks, calibration_warnings=list(dict.fromkeys(warnings)), model_response=data,
                seconds=response.get('seconds', 0), model=response.get('model'), usage=response.get('usage', {}),
                input_digest=digest, proposal_digest=hashlib.sha256(json.dumps(candidates, sort_keys=True).encode()).hexdigest())
