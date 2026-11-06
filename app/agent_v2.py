"""Choose a legal candidate, then independently validate the concrete decision."""
import json
from model_client import chat
from agent import Decision,validate_decision,encode
def candidates(state,side):
 result={'WAIT':dict(unit_id=0,action='WAIT',target_node=0)}
 nodes=sorted(n['id'] for n in state['nodes'])
 for u in state['entities']:
  if u['side']!=side or u['state'] in [4,6] or u['hp']<=0:continue
  choices=[('DEFEND',u['current_node'])]+[('MOVE',n) for n in nodes if n!=u['current_node']]
  adj=sorted({e[1] if e[0]==u['current_node'] else e[0] for e in state['edges'] if u['current_node'] in e[:2]})
  choices += [(action,n) for action in ['ATTACK','RETREAT'] for n in adj]
  for action,node in choices:
   value=dict(tick=state['tick'],unit_id=u['id'],action=action,target_node=node,evidence=[],reason='candidate')
   d=Decision(**value)
   if not validate_decision(d,state,side,set()):result[f"{u['id']}:{action}:{node}"]={k:value[k] for k in ['unit_id','action','target_node']}
 return result
def propose(retriever,state,side,instruction,mode='hybrid',config=None):
 rows=[] if mode=='none' else retriever.retrieve('指令状态约束 DEFEND MOVE '+instruction,3,'hybrid')
 allowed=candidates(state,side);short={'S'+str(i+1):r for i,r in enumerate(rows)}
 schema={'type':'object','additionalProperties':False,'properties':{'choice':{'type':'string','enum':list(allowed)},'reason':{'type':'string','maxLength':180},'evidence':{'type':'array','maxItems':3,'items':{'type':'string','enum':list(short) if short else ['NO_EVIDENCE']}}},'required':['choice','reason','evidence']}
 prompt=dict(side=side,observation=state,instruction=instruction,legal_candidates=allowed,evidence=[dict(source_id=k,status=r['status'],text=r['text']) for k,r in short.items()])
 raw=chat([dict(role='system',content='你是节点仿真代理。严格遵守当前任务意图，只能从legal_candidates选择一个动作。没有合法动作或不可控时选择WAIT。证据只解释静态规则；当前观测才是动态事实。不要从证据猜测不可见敌人。证据编号只从提供列表选择；没有使用证据时返回空数组。reason写一句简短依据。'),dict(role='user',content=json.dumps(prompt,ensure_ascii=False))],max_tokens=256,schema=schema,config=config)
 try:
  payload=json.loads(raw['text']);value=allowed[payload['choice']];cites=[short[k]['id'] for k in payload['evidence'] if k in short]
  if len(cites)!=len(payload['evidence']):raise ValueError('unknown evidence')
  d=Decision(tick=state['tick'],**value,evidence=cites,reason=payload['reason']);errors=validate_decision(d,state,side,{r['id'] for r in rows})
  if raw['finish_reason']=='length':errors.append('truncated_generation')
  raw.update(decision=d.model_dump(),accepted=not errors,errors=errors,packet_hex=encode(d).hex() if not errors else '',choice=payload['choice'])
 except (ValueError,KeyError,TypeError) as e:raw.update(decision=None,accepted=False,errors=['invalid_proposal:'+str(e)],packet_hex='')
 raw.update(mode=mode,side=side,evidence_ids=[r['id'] for r in rows],candidate_count=len(allowed),recipe='legal_candidate_v2');return raw
