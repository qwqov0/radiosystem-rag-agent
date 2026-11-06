"""Inspectable joint-plan proposals, independent of hidden state and memory.

The model selects among these proposals; generation is not an LLM achievement.
Identical present observations always produce identical proposals.
"""
import heapq
from battle_agent_v3 import distances

INACTIVE={'DESTROYED','SURRENDERED','ROUTED','RALLYING','EXITED'}
SPEED={'infantry':1.,'light':1.4,'tank':1.2,'artillery':.65}

def graph(obs):
 adj={n['id']:[] for n in obs['nodes']}
 for a,b,c in obs['edges']:adj[a].append((b,c));adj[b].append((a,c))
 return adj

def hop_distances(obs,start):
 adj=graph(obs);d={start:0};q=[start]
 for n in q:
  for v,_ in adj[n]:
   if v not in d:d[v]=d[n]+1;q.append(v)
 return d

def route(obs,start,goal,role,safe=False):
 adj=graph(obs);nodes={n['id']:n for n in obs['nodes']};side=obs['perspective']
 enemies=[e for e in obs['entities'] if e['side']!=side and e['status'] not in ('DESTROYED','SURRENDERED','EXITED')]
 costs={'infantry':[1.25,1.4,1,1.6],'light':[1.25,1,1,1.6],'tank':[2.2,2.8,1,1.9],'artillery':[1.25,1.4,1,1.84]}[role]
 d={start:0};previous={};q=[(0,start)]
 while q:
  cost,n=heapq.heappop(q)
  if cost!=d[n]:continue
  if n==goal:break
  for v,w in adj[n]:
   if safe and any(e['current_node']==v for e in enemies):continue
   risk=sum(12 for e in enemies if hop_distances(obs,e['current_node']).get(v,999)<= (3 if e['role']=='artillery' else 1)) if safe else 0
   value=cost+w*costs[nodes[v]['terrain']]/SPEED[role]+risk
   if value<d.get(v,1e20):d[v]=value;previous[v]=n;heapq.heappush(q,(value,v))
 if goal not in d:return [],None
 path=[];n=goal
 while n!=start:path.append(n);n=previous[n]
 return list(reversed(path)),round(d[goal],2)

def plans(obs):
 side=obs['perspective'];nodes={n['id']:n for n in obs['nodes']}
 own=sorted((u for u in obs['entities'] if u['side']==side and u['status'] not in INACTIVE),key=lambda u:u['id'])
 foes=[u for u in obs['entities'] if u['side']!=side and u['status'] not in ('DESTROYED','SURRENDERED')]
 objectives=sorted((o['node'] for o in obs['objectives']),key=lambda n:(nodes[n]['y'],nodes[n]['x']))
 if not objectives:objectives=sorted({u['current_node'] for u in own})
 if not own:return []
 variants=[('advance','分路争夺目标','balanced'),('screen_north','侦察并加强北侧通道','north'),('screen_south','侦察并加强南侧通道','south'),('pincer','正面牵制并侧翼机动','pincer'),('withdraw','脱离接触、保全部队','withdraw'),('hold','维持阵地、保持在途命令','hold')]
 results=[];controlled={u['id'] for u in own};occupied={e['current_node'] for e in foes}
 for pid,title,kind in variants:
  if kind=='pincer' and (sum(u['role']!='artillery' for u in own)<2 or not any(u['role']=='light' for u in own)):continue
  orders=[];assignments=[];warnings=[]
  reserve=sorted(own,key=lambda u:(u['role']=='artillery',u.get('under_fire',False),-u.get('morale',100),u['id']))[0]
  for idx,u in enumerate(own):
   start=u['current_node'];d=distances(obs,start,u['role'])
   urgent=u.get('morale',100)<38 or u.get('ammo',1)==0
   action='DEFEND';goal=start;task='坚守阵地'
   if urgent or kind=='withdraw':
    def safety(n):
     threat=sum(max(0,4-hop_distances(obs,e['current_node']).get(n,99))*35 for e in foes)
     rear=nodes[n]['x'] if side=='red' else -nodes[n]['x']
     return threat+rear*.12+d[n]*2
    safe=[n for n in d if n!=start and n not in occupied and route(obs,start,n,u['role'],True)[1] is not None]
    if safe:goal=min(safe,key=safety);action='RETREAT';task='低士气/缺弹撤离' if urgent else '有序脱离接触'
    else:warnings.append(f'{u["id"]}未找到安全撤退路径');task='退路受阻，暂时防御'
   elif kind=='hold':
    if u.get('route'):task='继续既有行军';action='CONTINUE'
   elif kind in ('north','south'):
    focus=objectives[0] if kind=='north' else objectives[-1]
    if u['id']==reserve['id'] or u['role']=='light':goal=focus;action='ATTACK';task='侦察并屏护该侧通道'
    elif u.get('route'):action='CONTINUE';task='保留主力既有计划'
    elif start not in objectives and u['role']!='artillery':goal=min(objectives,key=lambda n:d.get(n,1e20));action='ATTACK';task='主力继续争点'
   elif kind=='pincer' and len(own)>1 and u['role']!='artillery':
    focus=min(objectives,key=lambda n:d.get(n,1e20));approaches=[n for n,_ in graph(obs)[focus] if n not in occupied]
    if u['role']=='light' and approaches:
     goal=max(approaches,key=lambda n:abs(nodes[n]['y']-nodes[start]['y'])-d.get(n,1e20)*.4);action='MOVE';task='侧翼机动，形成另一接敌方向'
    else:goal=focus;action='ATTACK';task='正面牵制与占领'
   elif u['role']!='artillery':
    goal=objectives[idx%len(objectives)] if u['role']=='light' else min(objectives,key=lambda n:d.get(n,1e20)+25*(u['role']=='tank' and nodes[n]['terrain'] in (0,1)))
    action='ATTACK';task='分路争夺目标'
   # Artillery support positions keep at least two hops from a known threat
   # or the chosen objective; indirect fire still needs real friendly spotting.
   if u['role']=='artillery' and not urgent and kind not in ('hold','withdraw'):
    focus=objectives[0] if kind=='north' else objectives[-1] if kind=='south' else min(objectives,key=lambda n:d.get(n,1e20))
    hd=hop_distances(obs,focus)
    safe=[n for n in d if 2<=hd.get(n,99)<=3 and n not in occupied and all(hop_distances(obs,e['current_node']).get(n,99)>=2 for e in foes)]
    if safe:goal=min(safe,key=lambda n:d[n]*2+(0 if nodes[n]['terrain']==3 else 5));action='MOVE';task='保持间距，建立炮火支援阵地'
    else:goal=start;action='DEFEND';task='保护炮兵，等待观察条件'
   if action=='CONTINUE':path=u.get('route',[]);eta=None
   else:
    if goal==start:action='DEFEND'
    path,eta=route(obs,start,goal,u['role'],action=='RETREAT')
    if eta is None:goal=start;action='DEFEND';path=[];eta=0;warnings.append(f'{u["id"]}路线不可达')
    orders.append(dict(side=side,unit_id=u['id'],action=action,target_node=goal))
   assignments.append(dict(unit_id=u['id'],role=u['role'],task=task,action=action,target_node=goal,route=path,estimated_ticks=eta))
  risks=[]
  for o in orders:
   u=next(u for u in own if u['id']==o['unit_id']);t=nodes[o['target_node']]['terrain']
   if u['role']=='tank' and t in (0,1) and o['action'] not in ('RETREAT','DEFEND'):risks.append('坦克目标位于复杂地形，需步兵配合')
  results.append(dict(id=pid,title=title,sector=kind,orders=orders,assignments=assignments,risks=list(dict.fromkeys(risks+warnings))))
 return results

def execution_feedback(obs,previous=None):
 if not previous:return dict(previous_plan=None,age_ticks=0,units=[],replan_reasons=['首次建立计划'])
 current={u['id']:u for u in obs['entities'] if u['side']==obs['perspective']}
 issued=previous.get('friendly_at_issue',{});feedback=[];reasons=[]
 for order in previous.get('orders',[]):
  uid=order['unit_id'];u=current.get(uid);old=issued.get(str(uid),{})
  state='不可见/不存在' if u is None else '已按任务脱离战场' if u['status']=='EXITED' else '失去控制' if u['status'] in INACTIVE else '已到达' if u['current_node']==order['target_node'] else '执行中' if u.get('route') else '未到达且无在途路线'
  loss=round(old.get('hp',u.get('hp',0) if u else 0)-(u.get('hp',0) if u else 0),2)
  feedback.append(dict(unit_id=uid,result=state,hp_loss=loss,goal=order['target_node']))
  if u and (u.get('morale',100)<38 or u.get('flanked')):reasons.append(f'{uid}士气/侧翼危险')
  if state in ('失去控制','未到达且无在途路线'):reasons.append(f'{uid}计划执行受阻')
 return dict(previous_plan=previous.get('selected_plan'),age_ticks=obs['tick']-previous.get('source_tick',obs['tick']),units=feedback,replan_reasons=list(dict.fromkeys(reasons)))

def triggers(obs,previous_obs=None):
 if previous_obs is None:return ['initial']
 before={u['id']:u for u in previous_obs['entities']};reasons=[];side=obs['perspective']
 for u in obs['entities']:
  old=before.get(u['id'])
  if u['side']!=side and old is None:reasons.append('new_contact')
  if u['side']==side and old:
   if u.get('flanked') and not old.get('flanked'):reasons.append('flanked')
   if u.get('morale',100)<38<=old.get('morale',100):reasons.append('low_morale')
   if u['status'] in INACTIVE and u['status']!='EXITED' and old['status'] not in INACTIVE:reasons.append('unit_lost_control')
 if any(u['side']!=side and u['id'] not in {v['id'] for v in obs['entities']} and u['status'] not in ('DESTROYED','SURRENDERED') for u in previous_obs['entities']):reasons.append('lost_contact')
 if obs.get('objectives')!=previous_obs.get('objectives'):reasons.append('objective_changed')
 task,old_task=obs.get('own_mission',{}),previous_obs.get('own_mission',{})
 if task:
  if task.get('kind')!=old_task.get('kind'):reasons.append('mission_phase_changed')
  if task.get('completed')!=old_task.get('completed'):reasons.append('mission_progress')
  if task.get('remaining_ticks',999)<=16<old_task.get('remaining_ticks',999):reasons.append('deadline_close')
 if any(u['side']==side and u['status']=='EXITED' and before.get(u['id'],{}).get('status')!='EXITED' for u in obs['entities']):
  reasons.append('mission_progress')
 return sorted(set(reasons))
