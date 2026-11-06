"""v4 commander: retrieve -> competing intent hypotheses -> joint-plan choice.

Planning proposals and legal checks are deterministic scaffolding. Only the
hypotheses, evidence selection and proposal choice are attributed to the LLM.
"""
import hashlib, json
from battle_memory import RULES
from battle_planner import plans, execution_feedback

INTENTS={'unknown':'意图不明','recon':'侦察试探','assault':'正面进攻','flank':'侧翼机动','withdraw':'撤离整顿'}
SECTORS={'north':'北侧','south':'南侧','central':'中路','unknown':'方向未明'}

def decide(obs,memory,mode='memory'):
 from model_client import chat
 context=memory.decision_context(obs,mode)
 previous=getattr(memory,'previous_plan',None)
 return decide_context(obs,context,previous,chat)

def decide_context(obs,context,previous=None,infer=None):
 if infer is None:
  from model_client import chat
  infer=chat
 candidates=plans(obs);feedback=execution_feedback(obs,previous)
 if previous:
  latest={t['unit_id']:t for t in context['tracks']};updates=[]
  for hypothesis in previous.get('intent',[]):
   uid=hypothesis.get('enemy_id');track=latest.get(uid)
   update='仍无新目击，原假设未获确认'
   if track and track['status']=='confirmed_destroyed':update='新观察确认该单位失去战力，停止沿用其继续行动的假设'
   elif track and track['last_seen_tick']>previous.get('source_tick',-1):
    update='获得同侧新目击，可继续核查原假设' if track['sector']==hypothesis.get('focus_sector') else '新目击出现在另一侧，需要修正原方向判断'
   updates.append(dict(enemy_id=uid,previous_hypothesis=hypothesis.get('hypothesis'),previous_confidence=hypothesis.get('confidence'),
    update=update,new_observation=track))
  feedback['hypothesis_updates']=updates
 base=dict(agent_version='commander_v4',controller=context['mode'],source_tick=obs['tick'],
  evidence=context['evidence'],tracks=context['tracks'],retrieval_query=context['query'],
  feedback=feedback,history_frames_omitted=context.get('history_frames_omitted',0),
  candidate_plans=candidates,proposal_origin='deterministic_joint_planner',choice_origin='local_llm',
  friendly_at_issue={str(u['id']):dict(hp=u['hp'],morale=u.get('morale',100),node=u['current_node']) for u in obs['entities'] if u['side']==obs['perspective']})
 if not candidates:
  return dict(**base,orders=[],intent=[],plan='部队暂不可控，等待安全整顿',reconsider_when='部队恢复控制',selected_plan=None,grounding_passed=True,seconds=0)
 active=[t for t in context['tracks'] if t['status']!='confirmed_destroyed']
 source_by_id={e['id']:e for e in context['evidence']}
 enemy_ids={t['unit_id'] for t in active}
 support_ids=[e['id'] for e in context['evidence'] if e.get('unit_id') in enemy_ids and ('敌军' in e['text'])]
 own=[u for u in obs['entities'] if u['side']==obs['perspective']]
 visible=[u for u in obs['entities'] if u['side']!=obs['perspective'] and u['status'] not in ('DESTROYED','SURRENDERED')]
 # This pruning depends only on the CURRENT observation, and is shared by all
 # ablations. It cannot encode which historic flank an evaluator expects.
 idle=not visible and not any(u.get('route') for u in own) and not any(o.get('owner')==obs['perspective'] for o in obs['objectives'])
 critical=any(u.get('morale',100)<38 or u.get('ammo',1)==0 for u in own)
 eligible=[p for p in candidates if not (p['id']=='hold' and idle and not critical) and not (p['id']=='withdraw' and not visible and not critical)]
 schema={'type':'object','additionalProperties':False,'properties':{
  'assessments':{'type':'array','minItems':1 if active else 0,'maxItems':3 if active else 0,'items':{
   'type':'object','additionalProperties':False,'properties':{
    'enemy_id':{'type':'integer','enum':sorted(enemy_ids) or [0]},
    'intent':{'type':'string','enum':list(INTENTS)},
    'focus_sector':{'type':'string','enum':list(SECTORS)},
    'confidence':{'type':'string','enum':['low','medium']},
    'support':{'type':'array','minItems':1,'maxItems':3,'items':{'type':'string','enum':support_ids or ['NO_CONTACT']}},
    'counter_evidence':{'type':'array','maxItems':2,'items':{'type':'string','enum':support_ids or ['NO_CONTACT']}},
    'basis':{'type':'string','maxLength':110}},
   'required':['enemy_id','intent','focus_sector','confidence','support','counter_evidence','basis']}},
  'selected_plan':{'type':'string','enum':[p['id'] for p in eligible]},
  'choice_reason':{'type':'string','maxLength':180},
  'reconsider_when':{'type':'array','minItems':1,'maxItems':3,'items':{'type':'string','enum':['new_contact','lost_contact','flanked','low_morale','objective_changed','unit_lost_control','plan_blocked','periodic']}}},
  'required':['assessments','selected_plan','choice_reason','reconsider_when']}
 # Keep the perceptual facts near the final question; avoid making a 7B model
 # reconstruct a battlefield from hundreds of repeated JSON keys.
 prompt=dict(mission='争夺公开目标；保持兵力与士气；用已知历史选择应对。',
  current=dict(tick=obs['tick'],side=obs['perspective'],friendlies=own,visible_enemies=visible,objectives=obs['objectives']),
  map=[dict(id=n['id'],terrain=n['terrain_name'] if 'terrain_name' in n else n['terrain'],x=n['x'],y=n['y']) for n in obs['nodes']],
  roads=obs['edges'],previous_plan_feedback=feedback,
  proposals=[{k:p[k] for k in ('id','title','sector','assignments','risks')} for p in eligible],
  rules={k:v for k,v in RULES.items() if k!='RULE_ARTILLERY' or any(u['role']=='artillery' for u in own)},
  recent_observations=context.get('recent',[]),
  temporal_query=context['query'],enemy_tracks=context['tracks'],retrieved_evidence=context['evidence'],
  question='先比较敌方可能的目的及反证，再从提案选择一项。最后目击在哪一侧，优先核查该侧；不能凭空知道失联敌人的当前位置。不要把失联直接当成撤退。每个判断至少引用一条对应敌军的直接证据，其他已观察敌军的证据可用于解释协同关系或提供反证。没有敌情时主动侦察争点，不编造对手意图。输出简短决策依据，不复述通用兵种教材。')
 response=infer([dict(role='system',content='你是节点战棋的指挥决策模型。事实来自当前观测和带时间的己方历史；历史位置不代表现在位置。不同意图是待验证假设，不是已确认事实。比较假设，选择一个已列出的多单位提案。不得修改提案或安排不存在的部队。模型只负责假设和选择，规则引擎执行。证据相关性与战果都会被复核。'),dict(role='user',content=json.dumps(prompt,ensure_ascii=False,separators=(',',':')))],max_tokens=800,schema=schema)
 if response.get('finish_reason')=='length':raise ValueError('truncated_decision')
 data=json.loads(response['text']);errors=[];warnings=[];checks=[]
 if data.get('selected_plan') not in [p['id'] for p in eligible]:raise ValueError('invalid_plan_choice')
 tracks={t['unit_id']:t for t in active}
 for a in data.get('assessments',[]):
  uid=a.get('enemy_id');track=tracks.get(uid)
  if not track:errors.append('unknown_enemy');continue
  if a.get('intent') not in INTENTS or a.get('focus_sector') not in SECTORS or a.get('confidence') not in ('low','medium'):errors.append('invalid_assessment')
  if not a.get('support'):errors.append('unsupported_assessment')
  direct_support=False
  for eid in a.get('support',[])+a.get('counter_evidence',[]):
   e=source_by_id.get(eid);ok=bool(e and e.get('unit_id') in {t['unit_id'] for t in context['tracks']} and e['tick']<=obs['tick'] and '敌军' in e['text'])
   same=bool(e and e.get('unit_id')==uid)
   if eid in a.get('support',[]) and same and ok:direct_support=True
   checks.append(dict(id=eid,enemy_id=uid,source_time_and_unit_valid=ok,direct_unit_match=same,usage='direct' if same else 'observed_context'))
   if not ok:errors.append('unrelated_or_unknown_evidence')
  if not direct_support:errors.append('no_direct_evidence_for_assessed_unit')
  if track['age']>12 and a['confidence']=='medium':warnings.append(f'{uid}敌情已陈旧，模型把握需下调复核')
 if active and not data.get('assessments'):errors.append('missing_assessment')
 if not active and data.get('assessments'):errors.append('invented_enemy')
 chosen=next(p for p in eligible if p['id']==data['selected_plan'])
 # Narration is separate from executable assignments, so unsupported prose
 # cannot manufacture units or mutate validated routes.
 role_set={u['role'] for u in obs['entities']}|{t['role'] for t in context['tracks']}
 for role,word in [('tank','坦克'),('artillery','炮兵'),('light','轻步兵')]:
  text=data['choice_reason']+' '.join(a['basis'] for a in data.get('assessments',[]))
  if role not in role_set and word in text:warnings.append('依据提及未部署兵种：'+word)
 intents=[]
 for a in data.get('assessments',[]):
  t=tracks.get(a['enemy_id'],{})
  intents.append(dict(hypothesis=f"敌军{a['enemy_id']}：{INTENTS.get(a['intent'],'未知')} / {SECTORS.get(a['focus_sector'],'未知')}",
   confidence=a['confidence'],evidence=a['support'],counter_evidence=a['counter_evidence'],basis=a['basis'],
   enemy_id=a['enemy_id'],intent_type=a['intent'],focus_sector=a['focus_sector'],last_seen_node=t.get('last_seen_node'),age=t.get('age')))
 conditions=list(dict.fromkeys(data['reconsider_when']))
 return dict(**base,policy_revision='v4.1_contextual_evidence',intent=intents,selected_plan=chosen['id'],plan=chosen['title'],choice_reason=data['choice_reason'],
  assignments=chosen['assignments'],orders=chosen['orders'] if not errors else [],
  reconsider_when=' / '.join(conditions),trigger_conditions=conditions,
  grounding_passed=not errors,grounding_errors=sorted(set(errors)),evidence_checks=checks,calibration_warnings=warnings,
  model_response=data,seconds=response.get('seconds',0),model=response.get('model'),usage=response.get('usage',{}),
  proposal_digest=hashlib.sha256(json.dumps(candidates,sort_keys=True).encode()).hexdigest())
