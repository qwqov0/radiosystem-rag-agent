"""Single-owner battle coordinator. Simulation never waits for model inference."""
from pathlib import Path
import json, os, queue, subprocess, threading, time, uuid
from battle_memory import BattleMemory
from battle_agent import scripted_orders, decide
from battle_planner import triggers
ROOT=Path(__file__).resolve().parent
ENGINE=Path(os.environ.get('RADIOSYSTEM_BATTLE_ENGINE',str(ROOT.parent/'engine/build'/('BattleSim_v5.exe' if os.name=='nt' else 'BattleSim_v5'))))

class BattleProcess:
 def __init__(self):
  env=os.environ.copy();env['PATH']=os.environ.get('PATH','')
  self.process=subprocess.Popen([str(ENGINE)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,env=env)
  self.q=queue.Queue()
  def read():
   for line in self.process.stdout:self.q.put(line)
   self.q.put(None)
  threading.Thread(target=read,daemon=True).start()
 def request(self,data):
  self.process.stdin.write(json.dumps(data,ensure_ascii=False)+'\n');self.process.stdin.flush()
  line=self.q.get(timeout=15)
  if line is None:raise RuntimeError('BattleSim exited')
  out=json.loads(line)
  if out.get('type')=='ERROR':raise ValueError(out['message'])
  return out
 def close(self):
  if self.process.poll() is None:
   self.process.stdin.close()
   try:self.process.wait(timeout=3)
   except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
  self.process.stdout.close()

class BattleService:
 def __init__(self):
  self.lock=threading.RLock();self.stop=threading.Event();self.engine=BattleProcess()
  self.running=False;self.interval=.8;self.controllers={'red':'scripted','blue':'scripted'}
  self.busy={'red':False,'blue':False};self.last_request={'red':-100,'blue':-100};self.traces=[]
  self.reset()
  self.worker=threading.Thread(target=self._loop,daemon=True);self.worker.start()
 def reset(self,scenario=None):
  with self.lock:
   self.running=False
   req={'command':'reset'}
   if scenario is not None:req['scenario']=scenario
   # Validate/load C++ before switching memory stores.
   state=self.engine.request(req)
   if hasattr(self,'memory'):self.memory.close()
   self.match_id=uuid.uuid4().hex[:12];self.directory=ROOT/'results/battle_v3'/self.match_id
   self.directory.mkdir(parents=True,exist_ok=True);self.memory=BattleMemory(self.directory/'memory.sqlite')
   self.frames=[];self.traces=[];self.last_request={'red':-100,'blue':-100};self.busy={'red':False,'blue':False}
   self.pending_triggers={'red':['initial'],'blue':['initial']};self.previous_decision_observations={}
   self.state=state;self._capture();self._save_frame()
   return self.view()
 def _capture(self):
  self.observations={}
  for side in ('red','blue'):
   obs=self.engine.request({'command':'state','side':side});self.observations[side]=obs;self.memory.observe(obs)
 def _save_frame(self):
  self.frames.append(self.state)
  with (self.directory/'frames.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(self.state,ensure_ascii=False)+'\n')
 def view(self,side='observer'):
  with self.lock:
   state=self.state if side=='observer' else self.observations[side]
   traces=self.traces[-16:] if side=='observer' else [t for t in self.traces if t['side']==side][-8:]
   return dict(match_id=self.match_id,state=state,running=self.running,interval=self.interval,controllers=self.controllers.copy(),busy=self.busy.copy(),decisions=traces,last_contacts={} if side=='observer' else {side:self.memory.last_contacts(state)})
 def step(self,ticks=1,orders=None,expected_tick=None):
  with self.lock:
   req=dict(command='step',ticks=ticks,orders=orders or [],expected_tick=self.state['tick'] if expected_tick is None else expected_tick)
   state=self.engine.request(req);self.state=state;self._capture()
   if not self.frames or self.frames[-1]['tick']!=state['tick'] or orders:self._save_frame()
   if state['winner']:self.running=False
   return self.view()
 def configure(self,running=None,interval=None,controllers=None):
  with self.lock:
   if running is not None:self.running=bool(running) and not bool(self.state['winner'])
   if interval is not None:self.interval=max(.2,min(4,float(interval)))
   if controllers:
    for side,mode in controllers.items():
     if side not in ('red','blue') or mode not in ('manual','scripted','memory','current','recent','full'):raise ValueError('invalid_controller')
    self.controllers.update(controllers)
   return self.view()
 def _trace(self,trace):
  self.traces.append(trace)
  with (self.directory/'decisions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(trace,ensure_ascii=False)+'\n')
 def request_decision(self,side):
  requested_at=time.perf_counter()
  with self.lock:
   mode=self.controllers[side]
   if self.busy[side] or mode=='manual' or self.state['winner']:return
   self.busy[side]=True;obs=json.loads(json.dumps(self.observations[side]));match=self.match_id
   self.last_request[side]=obs['tick']
   # Materialize all memory inputs under the match lock. A reset can close the
   # old SQLite store while the model runs without corrupting this job.
   previous=next((t for t in reversed(self.traces) if t.get('side')==side and t.get('accepted')),None)
   context=self.memory.decision_context(obs,mode,previous) if mode!='scripted' else None
   fired_triggers=list(self.pending_triggers[side]);self.pending_triggers[side]=[]
   self.previous_decision_observations[side]=obs
  class FrozenMemory:
   previous_plan=previous
   def decision_context(self,_obs,_mode):return context
  def work():
   try:
    if mode=='scripted':
     from mission_planner import scripted_decision
     data=scripted_decision(obs) if obs.get('own_mission') else dict(orders=scripted_orders(obs),plan='规则基线：步兵争点、轻步兵分路、坦克选地形、炮兵保持支援位置。',intent=[],evidence=[],controller=mode,source_tick=obs['tick'],reconsider_when='每6个节拍或关键战况变化',seconds=0)
    else:data=decide(obs,FrozenMemory(),mode)
    with self.lock:
     if match!=self.match_id:return
     trace=dict(side=side,**data);age=self.state['tick']-obs['tick'];trace['age_ticks']=age;trace['triggered_by']=fired_triggers;trace['wall_seconds']=time.perf_counter()-requested_at
     if self.controllers[side]!=mode:trace.update(accepted=False,error='controller_changed')
     elif age>16:trace.update(accepted=False,error='expired_decision')
     elif not data.get('grounding_passed',True):trace.update(accepted=False,error='grounding_rejected')
     else:
      # The C++ core revalidates ownership, control state, paths and the whole
      # batch against the NEW snapshot immediately before applying it.
      r=self.step(0,data['orders'],self.state['tick']);trace.update(accepted=self.state['batch_accepted'],applied_tick=self.state['tick'],order_checks=self.state['order_checks'])
     self._trace(trace)
   except Exception as e:
    with self.lock:
     if match==self.match_id:self._trace(dict(side=side,source_tick=obs['tick'],controller=mode,accepted=False,error=str(e),plan='决策失败，保留已有命令',intent=[],orders=[],evidence=[]))
   finally:
    with self.lock:
     if match==self.match_id:self.busy[side]=False
  threading.Thread(target=work,daemon=True).start()
 def _loop(self):
  deadline=time.monotonic()
  while not self.stop.wait(.08):
   try:
    with self.lock:
     if not self.running:deadline=time.monotonic();continue
     now=time.monotonic()
     if now<deadline:continue
     deadline=now+self.interval
     for side in (('red','blue') if (self.state['tick']//6)%2==0 else ('blue','red')):
      obs=self.observations[side]
      signals=triggers(obs,self.previous_decision_observations.get(side))
      self.pending_triggers[side]=sorted(set(self.pending_triggers[side]+signals))
      gap=obs['tick']-self.last_request[side]
      if gap>= (2 if self.pending_triggers[side] else 8):self.request_decision(side)
     self.step(1)
   except Exception as e:
    with self.lock:self.running=False;self._trace(dict(side='system',accepted=False,error=str(e),plan='引擎暂停，请检查错误',intent=[],orders=[],evidence=[]))
 def close(self):
  self.stop.set();self.worker.join(timeout=2)
  with self.lock:self.engine.close();self.memory.close()
