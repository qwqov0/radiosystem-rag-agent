"""Small local inference client shared by QA, experiments and decision agents."""
from pathlib import Path
import json,time,threading,urllib.request
ROOT=Path(__file__).resolve().parent
LOCK=threading.Lock()
def backend():
 p=ROOT/'runtime/backend.json'
 return json.loads(p.read_text(encoding='utf-8')) if p.exists() else dict(model='qwen2.5-3b-instruct-q4_k_m',url='http://127.0.0.1:18080/v1/chat/completions',device='cpu')
def chat(messages,max_tokens=512,schema=None,seed=42,config=None,cache_prompt=False):
 cfg=config or backend()
 body=dict(model=cfg['model'],messages=messages,temperature=0,seed=seed,max_tokens=max_tokens,cache_prompt=cache_prompt)
 if schema is not None:body['response_format']={'type':'json_schema','json_schema':{'name':'result','strict':True,'schema':schema}}
 key=(ROOT/'runtime/local_api_key.txt').read_text().strip()
 req=urllib.request.Request(cfg['url'],data=json.dumps(body,ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with LOCK:
  started=time.perf_counter()
  with urllib.request.urlopen(req,timeout=300) as f:r=json.load(f)
  elapsed=time.perf_counter()-started
 choice=r['choices'][0]
 return dict(text=choice['message']['content'],seconds=elapsed,usage=r.get('usage',{}),timings=r.get('timings',{}),finish_reason=choice.get('finish_reason'),model=cfg['model'],device=cfg.get('device'),backend_version=cfg.get('build'))
