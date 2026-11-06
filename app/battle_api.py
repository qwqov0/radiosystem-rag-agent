from pathlib import Path
from contextlib import asynccontextmanager
import sys, threading
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runtime/packages'))
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from battle_service import BattleService
from battle_scenarios import mechanism
from commander_cases import case
from mission_scenarios import mission_scenario

service=None
knowledge_retriever=None
knowledge_lock=threading.Lock()
@asynccontextmanager
async def lifespan(app):
 global service
 service=BattleService()
 service.reset(mission_scenario('hidden'))
 yield
 service.close()
app=FastAPI(title='RadioSystem Tactical Battle',version='5.0',lifespan=lifespan)
class Configuration(BaseModel):
 running:bool|None=None
 interval:float|None=Field(default=None,ge=.2,le=4)
 controllers:dict[str,str]|None=None
class Orders(BaseModel):
 orders:list[dict]=Field(default_factory=list,max_length=32)
 ticks:int=Field(default=0,ge=0,le=32)
 expected_tick:int|None=None
class Reset(BaseModel):
 scenario:str='default'
 swap_sides:bool=False
 rotate:bool=False
class Question(BaseModel):
 question:str=Field(min_length=1,max_length=2000)
 history:list[dict]=Field(default_factory=list,max_length=8)

@app.get('/knowledge',response_class=HTMLResponse)
def knowledge():return (ROOT/'battle_knowledge.html').read_text(encoding='utf-8')
@app.post('/api/chat')
def ask(req:Question):
 global knowledge_retriever
 try:
  from rag_v2 import Retriever,answer
  with knowledge_lock:
   if knowledge_retriever is None:knowledge_retriever=Retriever()
   result=answer(knowledge_retriever,req.question,'hybrid',3,req.history)
  return result
 except Exception as e:raise HTTPException(502,str(e))

@app.get('/',response_class=HTMLResponse)
def home():return (ROOT/'battle_ui.html').read_text(encoding='utf-8')
@app.get('/assets/battle_intel_v4.js')
def intel_script():return FileResponse(ROOT/'battle_intel_v4.js',media_type='application/javascript')
@app.get('/assets/battle_mission_v5.js')
def mission_script():return FileResponse(ROOT/'battle_mission_v5.js',media_type='application/javascript')
@app.get('/api/battle/state')
def state(side:str='observer'):
 if side not in ('observer','red','blue'):raise HTTPException(400,'invalid side')
 return service.view(side)
@app.post('/api/battle/configure')
def configure(req:Configuration):
 try:return service.configure(**req.model_dump(exclude_none=True))
 except ValueError as e:raise HTTPException(400,str(e))
@app.post('/api/battle/reset')
def reset(req:Reset):
 try:
  if req.scenario in ('breakthrough','hidden','hold_extract'):
   return service.reset(mission_scenario(req.scenario,swap_sides=req.swap_sides,rotate=req.rotate))
  if req.scenario in ('memory_north','memory_south'):
   cfg,opening=case(req.scenario.split('_')[1])
   with service.lock:
    service.reset(cfg);service.configure(controllers={'red':'manual','blue':'manual'})
    for tick in range(8):service.step(1,[opening] if tick==0 else [])
    service.configure(controllers={'red':'memory','blue':'manual'},interval=2)
    return service.view()
  return service.reset(None if req.scenario=='default' else mechanism(req.scenario))
 except ValueError as e:raise HTTPException(400,str(e))
@app.post('/api/battle/step')
def step(req:Orders):
 try:return service.step(req.ticks,req.orders,req.expected_tick)
 except (ValueError,KeyError) as e:raise HTTPException(400,str(e))
@app.post('/api/battle/decide/{side}')
def decide(side:str):
 if side not in ('red','blue'):raise HTTPException(400,'invalid side')
 service.request_decision(side);return dict(status='queued')
@app.get('/api/battle/rules')
def rules():
 with service.lock:return service.engine.request(dict(command='rules'))
@app.get('/api/battle/replay')
def replay(side:str='observer'):
 if side not in ('observer','red','blue'):raise HTTPException(400,'invalid side')
 with service.lock:
  if side=='observer':frames=list(service.frames)
  else:
   import json
   with service.memory.lock:rows=service.memory.db.execute('SELECT data FROM frames WHERE side=? ORDER BY tick',(side,)).fetchall()
   frames=[json.loads(raw) for (raw,) in rows]
  return dict(match_id=service.match_id,frames=frames,decisions=[d for d in service.traces if side=='observer' or d['side']==side])
@app.get('/health')
def health():return dict(status='ok',engine='BattleSim',rules='battle_v5.0',agent='commander_v5',match_id=service.match_id)
