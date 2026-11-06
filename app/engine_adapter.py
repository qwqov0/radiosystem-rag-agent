"""Single-owner JSONL bridge to the actual C++ classroom target."""
from pathlib import Path
import json,os,subprocess,threading,queue
ROOT=Path(__file__).resolve().parent
local_engine=ROOT.parent/'engine/build'/('CourseSim.exe' if os.name=='nt' else 'CourseSim')
ENGINE=Path(os.environ.get('RADIOSYSTEM_ENGINE',str(local_engine)))
class CppSession:
 def __init__(self,log_path=None):
  env=os.environ.copy();env['PATH']=os.environ.get('PATH','')
  (ROOT/'results').mkdir(exist_ok=True)
  self.log=open(log_path or ROOT/'results/engine_stderr.log','a',encoding='utf-8')
  self.process=subprocess.Popen([str(ENGINE)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',bufsize=1,env=env)
  self.queue=queue.Queue()
  def reader():
   for line in self.process.stdout:self.queue.put(line)
   self.queue.put(None)
  self.reader=threading.Thread(target=reader,daemon=True);self.reader.start()
 def request(self,data):
  self.process.stdin.write(json.dumps(data,ensure_ascii=False)+'\n');self.process.stdin.flush()
  try:line=self.queue.get(timeout=10)
  except queue.Empty:raise TimeoutError('C++ JSONL reply timeout')
  if line is None:raise RuntimeError('C++ process exited, code '+str(self.process.poll()))
  response=json.loads(line)
  if response.get('type')=='ERROR':raise ValueError(response['message'])
  return response
 def close(self):
  if self.process.poll() is None:
   self.process.stdin.close()
   try:self.process.wait(timeout=3)
   except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
  self.process.stdout.close();self.log.close()
 def __enter__(self):return self
 def __exit__(self,*args):self.close()
def observe(state,side):
 """Known map, all friendlies, enemies only on friendly nodes or one-hop neighbors."""
 if side not in ['red','blue']:raise ValueError('invalid side')
 friendly=[u for u in state['entities'] if u['side']==side];visible={u['current_node'] for u in friendly if u['hp']>0 and u['state']!=6}
 for a,b,*_ in state['edges']:
  if any(u['current_node']==a and u['hp']>0 and u['state']!=6 for u in friendly):visible.add(b)
  if any(u['current_node']==b and u['hp']>0 and u['state']!=6 for u in friendly):visible.add(a)
 units=[dict(u) for u in state['entities'] if u['side']==side or u['current_node'] in visible]
 return dict(tick=state['tick'],scenario=state['scenario'],objective_node=state['objective_node'],nodes=state['nodes'],edges=state['edges'],entities=units,visible_nodes=sorted(visible),observation_rule='one_hop_from_alive_friendly')
