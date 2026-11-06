"""Joint commander decisions: current observation + side-private event RAG."""
import heapq, json
from battle_memory import RULES

def distances(obs,start,role='infantry'):
 nodes={n['id']:n for n in obs['nodes']};adj={n:[] for n in nodes}
 for a,b,c in obs['edges']:adj[a].append((b,c));adj[b].append((a,c))
 costs={'infantry':[1.25,1.4,1,1.6],'light':[1.25,1,1,1.6],'tank':[2.2,2.8,1,1.9],'artillery':[1.25,1.4,1,1.84]}[role]
 d={start:0};q=[(0,start)]
 while q:
  cost,n=heapq.heappop(q)
  if cost!=d[n]:continue
  for to,w in adj[n]:
   nd=cost+w*costs[nodes[to]['terrain']]
   if nd<d.get(to,1e20):d[to]=nd;heapq.heappush(q,(nd,to))
 return d

def scripted_orders(obs):
 """Explicit, labelled rules baseline; never presented as an LLM decision."""
 side=obs['perspective'];own=[u for u in obs['entities'] if u['side']==side and u['status'] not in ('DESTROYED','SURRENDERED','ROUTED','RALLYING')]
 foes=[u for u in obs['entities'] if u['side']!=side and u['status'] not in ('DESTROYED','SURRENDERED')]
 nodes={n['id']:n for n in obs['nodes']};objectives=[o['node'] for o in obs['objectives']];out=[]
 for u in own:
  node=u['current_node'];d=distances(obs,node,u['role'])
  if u['morale']<38:
   candidates=[n for n in d if not any(e['current_node']==n for e in foes)]
   rear=lambda n:(nodes[n]['x'] if side=='red' else -nodes[n]['x'])+d[n]*4
   goal=min(candidates,key=rear) if candidates else node;action='RETREAT'
  elif u.get('route'):continue
  elif u['role']=='artillery':
   # Follow the line at a distance instead of assaulting the objective.
   friendly_front=[f['current_node'] for f in own if f['role']!='artillery']
   goal=min(d,key=lambda n:min((abs(nodes[n]['x']-nodes[f]['x'])+abs(nodes[n]['y']-nodes[f]['y']) for f in friendly_front),default=0)+d[n]*7+(0 if nodes[n]['terrain']==3 else 70))
   action='DEFEND' if goal==node else 'MOVE'
  elif node in objectives or u.get('under_fire'):goal=node;action='DEFEND'
  else:
   goal=min(objectives,key=lambda n:d.get(n,1e9)+(35 if u['role']=='tank' and nodes[n]['terrain'] in (0,1) else 0)) if objectives else node
   if u['role']=='light' and len(objectives)>1:goal=objectives[-1] if side=='red' else objectives[0]
   action='ATTACK' if goal!=node else 'DEFEND'
  out.append(dict(side=side,unit_id=u['id'],action=action,target_node=goal))
 return out

def decide(obs,memory,mode='memory'):
 from model_client import chat
 if mode not in ('memory','recent','current','full'):raise ValueError('unknown agent condition')
 events=memory.retrieve(obs) if mode=='memory' else []
 history=memory.recent(obs['perspective'],obs['tick'],1000 if mode=='full' else 3) if mode!='current' else []
 dropped_history=0
 if mode=='full':
  while history and len(json.dumps(history,ensure_ascii=False))>48000:
   history.pop(0);dropped_history+=1
 history_evidence=[]
 if mode in ('recent','full'):
  for frame in history:
   for u in frame['entities']:
    if u['side']!=obs['perspective']:history_evidence.append(dict(id=f"H{frame['tick']}U{u['id']}",tick=frame['tick'],unit_id=u['id'],node=u['current_node'],text=f"T{frame['tick']}目击敌军{u['id']}在{u['current_node']}号节点"))
 role_set={u['role'] for u in obs['entities']}
 rule_evidence=[dict(id=k,text=v) for k,v in RULES.items() if k!='RULE_ARTILLERY' or 'artillery' in role_set]
 contacts=[dict(id=f"O{u['id']}",tick=obs['tick'],unit_id=u['id'],node=u['current_node'],text=f"当前目击敌军{u['id']}（{u['role']}）在{u['current_node']}号节点") for u in obs['entities'] if u['side']!=obs['perspective']]
 evidence=events+history_evidence+contacts+rule_evidence;ids=[e['id'] for e in evidence]
 intent_ids=[e['id'] for e in events if '敌军' in e['text']]+[e['id'] for e in contacts+history_evidence]
 if not intent_ids:intent_ids=['NO_CONTACT']
 own=[u['id'] for u in obs['entities'] if u['side']==obs['perspective'] and u['status'] not in ('DESTROYED','SURRENDERED','ROUTED','RALLYING')]
 if not own:return dict(orders=[],intent=[],plan='等待部队整顿',reconsider_when='部队恢复控制',evidence=[],controller=mode,source_tick=obs['tick'])
 nodes=[n['id'] for n in obs['nodes']]
 unit_options={}
 for u in obs['entities']:
  if u['id'] not in own:continue
  reachable=sorted(distances(obs,u['current_node'],u['role']))
  unit_options[str(u['id'])]={'type':'string','enum':['CONTINUE',f"DEFEND:{u['current_node']}"]+[f'{a}:{n}' for a in ('MOVE','ATTACK','RETREAT') for n in reachable if n!=u['current_node']]}
 schema={'type':'object','additionalProperties':False,'properties':{
  'intent':{'type':'array','maxItems':3,'items':{'type':'object','additionalProperties':False,'properties':{
   'hypothesis':{'type':'string','maxLength':120},'confidence':{'type':'string','enum':['low'] if intent_ids==['NO_CONTACT'] else ['low','medium','high']},
   'evidence':{'type':'array','maxItems':4,'items':{'type':'string','enum':intent_ids}}},'required':['hypothesis','confidence','evidence']}},
  'plan':{'type':'string','maxLength':220},
  'orders':{'type':'object','additionalProperties':False,'properties':unit_options,'required':list(unit_options)},
  'reconsider_when':{'type':'string','maxLength':120}},'required':['intent','plan','orders','reconsider_when']}
 prompt=dict(observation=obs,evidence=evidence,mission='主动争夺公开目标，以合理损失取得更多控制积分；协调兵种、地形、侧翼和预备队。',
  command_format='orders为单位编号到动作字符串的映射。CONTINUE保留当前命令；DEFEND只能原地；MOVE/ATTACK/RETREAT:节点编号。所有单位不必同时改变计划。',
  intelligence_limits='只讨论本局实际存在的单位；规则中的兵种不代表本局已部署。优先分析最新敌军移动与最后目击位置，区分北/南/正面通道。若无敌军目击证据，只能低把握或说明情报不足；规则不能作为敌方战术证据。',
  known_friendly_roles=sorted({u['role'] for u in obs['entities'] if u['side']==obs['perspective']}))
 tracks={}
 node_info={n['id']:n for n in obs['nodes']};mid_y=(min(n['y'] for n in obs['nodes'])+max(n['y'] for n in obs['nodes']))/2
 for e in events+history_evidence:
  if '敌军' not in e['text']:continue
  if e['unit_id'] not in tracks or e['tick']>=tracks[e['unit_id']]['evidence_tick']:
   n=node_info[e['node']]
   tracks[e['unit_id']]=dict(unit_id=e['unit_id'],last_reported_node=e['node'],evidence_tick=e['tick'],sector='北侧' if n['y']<mid_y else '南侧',evidence_id=e['id'],status='历史目击，当前位置未知')
 prompt['historical_enemy_tracks']=list(tracks.values())
 prompt['decision_guidance']='围绕实际敌情与目标提出具体计划。若未占领目标且暂无敌情，考虑侦察并推进，而非无限原地防御。解释命令中每支实际单位的任务，不得安排不存在的兵种。'
 if mode in ('memory','recent'):prompt['recent_observations']=history
 if mode=='full':prompt['past_observations']=history;prompt['history_frames_omitted_for_context_budget']=dropped_history
 result=chat([dict(role='system',content='你是战棋指挥员。根据己方当前观测和提供的历史证据比较敌方意图假设，再下达协同命令。历史位置不是当前位置；看不见的敌人去向未知，禁止虚构目击。只能控制己方可控部队，每个单位最多一个命令；DEFEND目标必须是该单位当前节点。保留合理的在途计划，低士气提前撤退，炮兵依靠观察且避免近战，坦克避免独自突入森林城镇。用简短可核对的战术依据说明计划；引用证据编号。信息不足时明确低把握。'),dict(role='user',content=json.dumps(prompt,ensure_ascii=False))],max_tokens=850,schema=schema)
 if result['finish_reason']=='length':raise ValueError('truncated_decision')
 data=json.loads(result['text']);choices=data.pop('orders');orders=[]
 for uid,choice in choices.items():
  if uid not in unit_options or choice not in unit_options[uid]['enum']:raise ValueError('invalid_candidate')
  if choice=='CONTINUE':continue
  action,node=choice.split(':');orders.append(dict(unit_id=int(uid),action=action,target_node=int(node),side=obs['perspective']))
 data['orders']=orders;data['candidate_choices']=choices
 for intent in data['intent']:
  if any(e not in intent_ids for e in intent['evidence']):raise ValueError('unknown_evidence')
 warnings=[]
 dynamic=intent_ids!=['NO_CONTACT']
 if not dynamic and any(i['confidence']!='low' for i in data['intent']):warnings.append('当前无敌情证据，模型意图把握可能过高')
 # Report observable grounding failures rather than claiming a legal packet
 # proves sound tactics. The original model response remains in the trace.
 for role,word in [('artillery','炮兵'),('tank','坦克'),('light','轻步兵')]:
  if role not in role_set and word in data['plan']:warnings.append('计划提及本局未部署的兵种：'+word)
 data.update(controller=mode,source_tick=obs['tick'],evidence=evidence,seconds=result['seconds'],model=result['model'],usage=result.get('usage',{}),calibration_warnings=warnings,history_frames_omitted=dropped_history)
 return data
