"""Side-private, temporal battle memory. Only observations enter this store.

Retrieval combines exact unit/location matches, lexical event relevance and
recency. It is intentionally separate from the frozen source-code RAG corpus.
"""
from collections import Counter
from pathlib import Path
import json, math, re, sqlite3, threading

RULES = {
 'RULE_TERRAIN': '森林城镇提供步兵掩护，遮挡后续观察；高地扩大观察。轻步兵穿林成本低，坦克穿林和进城成本高。',
 'RULE_MATCHUP': '坦克在开阔地压制步兵；森林城镇中步兵反装甲效率上升、坦克反步兵效率下降。轻步兵适合绕行袭击炮兵。',
 'RULE_ARTILLERY': '炮兵射程3条边，依赖友军当前可见目标，距离不足2条边时火力大幅下降。炮击主要提供压制，必须有近战单位保护。',
 'RULE_FLANK': '两个直接火力方向夹角超过100度形成夹击，增加承伤和士气损失。同方向增兵只产生受正面宽度限制的兵力优势。',
 'RULE_MORALE': '士气20及以下溃散，不接受指令；脱离近敌并安全整顿至少10个节拍、士气恢复到40才能归队。提前主动撤退可保全部队。',
 'RULE_MEMORY': '历史目击只描述当时状态，敌人消失不等于已撤退或被消灭。比较多种意图假设，引用当时己方确实获得的证据。',
}

def tokens(text):
 words = re.findall(r'[a-z_]+|\d+', text.lower())
 for part in re.findall(r'[\u4e00-\u9fff]+', text):
  words.extend(part[i:i+2] for i in range(len(part)-1))
 return Counter(words)

class BattleMemory:
 def __init__(self, path):
  Path(path).parent.mkdir(parents=True, exist_ok=True)
  self.db = sqlite3.connect(path, check_same_thread=False)
  self.lock = threading.RLock()
  self.db.executescript('''CREATE TABLE IF NOT EXISTS frames(side TEXT,tick INT,data TEXT,PRIMARY KEY(side,tick));
   CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,side TEXT,tick INT,kind TEXT,unit INT,node INT,text TEXT);
   CREATE INDEX IF NOT EXISTS time_index ON events(side,tick);
   CREATE TABLE IF NOT EXISTS sightings(side TEXT,tick INT,unit INT,data TEXT,PRIMARY KEY(side,tick,unit));
   CREATE INDEX IF NOT EXISTS sighting_lookup ON sightings(side,unit,tick);''')

 def observe(self, obs):
  side, tick = obs['perspective'], obs['tick']
  if side not in ('red','blue'): raise ValueError('Observer state cannot enter agent memory')
  with self.lock, self.db:
   if self.db.execute('SELECT 1 FROM frames WHERE side=? AND tick=?',(side,tick)).fetchone(): return
   row = self.db.execute('SELECT data FROM frames WHERE side=? AND tick<? ORDER BY tick DESC LIMIT 1',(side,tick)).fetchone()
   previous = {u['id']:u for u in json.loads(row[0])['entities']} if row else {}
   current = {u['id']:u for u in obs['entities']}
   for uid, u in current.items():
    if u['side']!=side:
     self.db.execute('INSERT OR IGNORE INTO sightings VALUES(?,?,?,?)',(side,tick,uid,json.dumps(u,ensure_ascii=False)))
    old = previous.get(uid); relation = '友军' if u['side']==side else '敌军'
    changes = []
    if old is None: changes.append(('contact',f"首次目击{relation}{uid}（{u['role']}）位于{u['current_node']}号节点"))
    else:
     if old['current_node'] != u['current_node']: changes.append(('movement',f"{relation}{uid}从{old['current_node']}移动到{u['current_node']}"))
     if old['hp']-u['hp']>=1: changes.append(('loss',f"{relation}{uid}兵力从{old['hp']:.1f}降至{u['hp']:.1f}"))
     if u.get('morale',100)<40<=old.get('morale',100): changes.append(('morale',f"友军{uid}士气跌至{u['morale']:.1f}，存在溃散风险"))
     if u['status']!=old['status']: changes.append(('status',f"{relation}{uid}从{old['status']}转为{u['status']}"))
     if u.get('flanked') and not old.get('flanked'): changes.append(('flank',f"友军{uid}在{u['current_node']}遭到多方向夹击"))
    for kind,text in changes:
     self.db.execute('INSERT INTO events(side,tick,kind,unit,node,text) VALUES(?,?,?,?,?,?)',(side,tick,kind,uid,u['current_node'],text))
   for uid,u in previous.items():
    if uid not in current and u['side']!=side and u['status'] not in ('DESTROYED','SURRENDERED','EXITED'):
     self.db.execute('INSERT INTO events(side,tick,kind,unit,node,text) VALUES(?,?,?,?,?,?)',(side,tick,'lost_contact',uid,u['current_node'],f"敌军{uid}脱离视野，最后目击于{u['current_node']}；去向未知"))
   self.db.execute('INSERT INTO frames VALUES(?,?,?)',(side,tick,json.dumps(obs,ensure_ascii=False)))

 def retrieve(self, obs, k=8):
  """Exclude present/future events; query is built autonomously from this moment."""
  side, tick = obs['perspective'],obs['tick']
  relevant_units={u['id'] for u in obs['entities'] if u['side']!=side or u.get('under_fire') or u.get('morale',100)<45}
  places={u['current_node'] for u in obs['entities']}
  query='敌军 移动 消失 夹击 意图 迂回 撤退 '+ ' '.join(str(v) for v in relevant_units|places)
  qt=tokens(query)
  with self.lock:
   rows=self.db.execute('SELECT id,tick,kind,unit,node,text FROM events WHERE side=? AND tick<? ORDER BY tick DESC LIMIT 800',(side,tick)).fetchall()
  ranked=[]
  for eid, when, kind, uid, node, text in rows:
   terms=tokens(text); lexical=sum(min(n,terms[t]) for t,n in qt.items()) / math.sqrt(1+sum(terms.values()))
   score=lexical+ (5 if uid in relevant_units else 0)+(2 if node in places else 0)+(3 if '敌军' in text else 0)+{'lost_contact':3,'movement':3,'flank':4,'morale':3}.get(kind,0)+2/(1+(tick-when)/12)
   ranked.append(dict(id=f'M{eid:05d}',tick=when,kind=kind,unit_id=uid,node=node,text=text,score=round(score,3)))
  ranked.sort(key=lambda e:(-e['score'],-e['tick'],e['id']))
  # A repeated damage stream must not crowd all movement/last-contact evidence out.
  out=[]; counts=Counter()
  for event in ranked:
   key=(event['unit_id'],event['kind'])
   if counts[key]>=2: continue
   out.append(event);counts[key]+=1
   if len(out)>=k:break
  return sorted(out,key=lambda e:(e['tick'],e['id']))

 def recent(self, side, tick, limit=3):
  with self.lock:
   rows=self.db.execute('SELECT data FROM frames WHERE side=? AND tick<? ORDER BY tick DESC LIMIT ?',(side,tick,limit)).fetchall()
  return [dict(tick=o['tick'],entities=o['entities']) for (raw,) in reversed(rows) for o in [json.loads(raw)]]

 def last_contacts(self, obs):
  side,tick=obs['perspective'],obs['tick'];visible={u['id'] for u in obs['entities']};contacts={}
  with self.lock:
   rows=self.db.execute('SELECT data FROM frames WHERE side=? AND tick<=? ORDER BY tick DESC',(side,tick)).fetchall()
  for (raw,) in rows:
   frame=json.loads(raw)
   for u in frame['entities']:
    if u['side']!=side and u['id'] not in contacts:
     contacts[u['id']]=None if u['status'] in ('DESTROYED','SURRENDERED','EXITED') else dict(id=u['id'],role=u['role'],node=u['current_node'],tick=frame['tick'],age=tick-frame['tick'])
  return [u for uid,u in contacts.items() if uid not in visible and u is not None]

 def decision_context(self, obs, mode='memory', previous=None):
  """Temporal retrieval with explicit source IDs. No global replay is consulted.

  The memory condition retrieves each contact's last sighting/changed positions
  and relevant events. Other conditions only use their own permitted window.
  """
  if mode not in ('memory','current','recent','full'):raise ValueError('invalid memory mode')
  side,tick=obs['perspective'],obs['tick']
  if side not in ('red','blue'):raise ValueError('invalid perspective')
  history=self.recent(side,tick,1000 if mode=='full' else 3) if mode!='current' else []
  omitted=0
  while mode=='full' and history and len(json.dumps(history,ensure_ascii=False))>42000:
   history.pop(0);omitted+=1
  events=self.retrieve(obs,8) if mode=='memory' else []
  if mode=='memory':
   with self.lock:
    rows=self.db.execute('SELECT tick,unit,data FROM sightings WHERE side=? AND tick<=? ORDER BY tick DESC,unit',(side,tick)).fetchall()
  else:
   rows=[(f['tick'],u['id'],json.dumps(u)) for f in history for u in f['entities'] if u['side']!=side]
   rows.sort(key=lambda r:(-r[0],r[1]))
  # Current observations are authoritative even if a caller hasn't persisted
  # this tick yet; past frames can never replace them.
  rows=[(tick,u['id'],json.dumps(u)) for u in obs['entities'] if u['side']!=side]+rows
  grouped={}
  for when,uid,raw in rows:
   trail=grouped.setdefault(uid,[]);u=json.loads(raw)
   if len(trail)<4 and (not trail or u['current_node']!=trail[-1][1]['current_node']):trail.append((when,u))
  nodes={n['id']:n for n in obs.get('nodes',[])};visible=set(obs.get('visible_nodes',[]))
  middle=(min((n['y'] for n in nodes.values()),default=0)+max((n['y'] for n in nodes.values()),default=0))/2
  current={u['id'] for u in obs['entities'] if u['side']!=side}
  sources=list(events);tracks=[]
  for uid,trail in sorted(grouped.items()):
   when,last=trail[0];n=last['current_node'];point=nodes.get(n,{'y':middle,'terrain':2})
   status='confirmed_exited' if last['status']=='EXITED' else 'confirmed_destroyed' if last['status'] in ('DESTROYED','SURRENDERED') else ('visible' if uid in current else 'lost_contact')
   ids=[];positions=[]
   for t,u in reversed(trail):
    eid=f'F{t}U{uid}';ids.append(eid);positions.append(dict(tick=t,node=u['current_node']))
    sources.append(dict(id=eid,tick=t,kind='sighting',unit_id=uid,node=u['current_node'],text=f"T{t}实际目击敌军{uid}（{u['role']}）在{u['current_node']}号节点，状态{u['status']}"))
   tracks.append(dict(unit_id=uid,role=last['role'],last_seen_tick=when,last_seen_node=n,age=tick-when,status=status,
    sector='north' if point['y']<middle else 'south',positions=positions,evidence=ids,
    last_location_cleared=status=='lost_contact' and n in visible and point['terrain']!=1))
  # A scene can contain at most 16 opposing units. Bound model memory size
  # without silently adding raw whole-history input to the retrieval condition.
  result=dict(version='episodic_v4',mode=mode,query=dict(as_of_tick=tick,side=side,
   focus_units=sorted(u['id'] for u in obs['entities'] if u.get('under_fire') or u.get('morale',100)<40),
   focus_nodes=sorted({o['node'] for o in obs.get('objectives',[])}),requested=['last_sighting','movement','lost_contact','loss','flank']),
   tracks=tracks,evidence=list({e['id']:e for e in sources}.values()),
   recent=history if mode in ('recent','full') else history[-2:],history_frames_omitted=omitted)
  if obs.get('own_mission'):
   from mission_reasoning import augment_context
   result=augment_context(obs,result,self,previous)
  return result

 def close(self):
  with self.lock:self.db.close()
