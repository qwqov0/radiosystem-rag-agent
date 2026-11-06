from pathlib import Path
import sys,json,uuid,datetime,threading,urllib.request
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runtime/packages'))
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
from rag_v2 import Retriever,answer
from agent_v2 import propose
from model_client import backend
app=FastAPI(title='RadioSystem local RAG and Agent lab',version='0.2.0')
retriever=None;log_lock=threading.Lock()
class Ask(BaseModel):
 question:str=Field(min_length=1,max_length=2000)
 mode:str='hybrid'
 k:int=Field(default=3,ge=1,le=8)
 history:list[dict]=Field(default_factory=list,max_length=8)
class Act(BaseModel):
 state:dict
 side:str=Field(pattern='^(red|blue)$')
 instruction:str=Field(min_length=1,max_length=1000)
 mode:str='hybrid'
def log(kind,result):
 out=ROOT/'results';out.mkdir(exist_ok=True)
 record=dict(id=str(uuid.uuid4()),time=datetime.datetime.now(datetime.timezone.utc).isoformat(),kind=kind,result=result)
 with log_lock,(out/'api_calls.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
 return record['id']
@app.on_event('startup')
def startup():
 global retriever
 retriever=Retriever()
@app.get('/health')
def health():
 cfg=backend();model_health='unavailable'
 try:
  with urllib.request.urlopen(cfg['url'].split('/v1/')[0]+'/health',timeout=3) as f:model_health=json.load(f).get('status','unknown')
 except Exception:pass
 return dict(status='ok' if model_health=='ok' else 'model_unavailable',model_status=model_health,chunks=len(retriever.rows),backend=cfg,knowledge_version='initial_source_snapshot_20261022',engine_execution='decision_endpoint_dry_run; separate_CppSession_episode_available',replay_available=(ROOT/'results/agent_gpu/episode.json').exists())
@app.post('/api/chat')
def chat(req:Ask):
 if req.mode not in ['none','closedbook','dense','hybrid']:raise HTTPException(400,'mode must be none/closedbook/dense/hybrid')
 try:r=answer(retriever,req.question,req.mode,req.k,req.history);r['trace_id']=log('chat',r);return r
 except Exception as e:raise HTTPException(502,str(e))
@app.post('/api/agent/decide')
def decide(req:Act):
 if req.mode not in ['none','hybrid']:raise HTTPException(400,'invalid mode')
 try:r=propose(retriever,req.state,req.side,req.instruction,req.mode);r['trace_id']=log('agent_dry_run',r);return r
 except Exception as e:raise HTTPException(422,str(e))
@app.get('/',response_class=HTMLResponse)
def index():return (ROOT/'ui_gpu.html').read_text(encoding='utf-8')
@app.get('/api/replay')
def replay():
 path=ROOT/'results/agent_gpu/episode.json'
 if not path.exists():raise HTTPException(404,'C++ Agent episode has not finished yet')
 return json.loads(path.read_text(encoding='utf-8'))
