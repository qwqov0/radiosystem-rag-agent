"""Frozen, source-grounded temporal probe. This is not a tactical win-rate study."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,functools,hashlib,json
from battle_service import BattleProcess,ENGINE
from battle_memory import BattleMemory
from battle_planner import plans
from battle_commander import decide_context
from commander_cases import case
from model_client import chat,backend

ROOT=Path(__file__).resolve().parent
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
def prepare(engine,direction,variant,memory):
 cfg,opening=case(direction,variant);engine.request(dict(command='reset',scenario=cfg));frames=[]
 for tick in range(9):
  obs=engine.request(dict(command='state',side='red'));memory.observe(obs);frames.append(obs)
  if tick<8:engine.request(dict(command='step',ticks=1,orders=[opening] if tick==0 else []))
 return obs,frames

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--tag',default='development');ap.add_argument('--variants',type=int,default=1);ap.add_argument('--start-variant',type=int,default=0);ap.add_argument('--modes',nargs='+',default=['current','recent','memory','full']);args=ap.parse_args()
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=ROOT/'results/commander_v4'/(args.tag+'_'+stamp);out.mkdir(parents=True,exist_ok=False)
 cfg=backend();files=['battle_commander.py','battle_planner.py','battle_memory.py','commander_cases.py','run_commander_eval.py']
 protocol=dict(kind='temporal_evidence_development_probe',frozen_at_utc=stamp,modes=args.modes,variants=list(range(args.start_variant,args.start_variant+args.variants)),directions=['north','south'],seed=42,max_tokens=800,temperature=0,model=cfg,
  engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(),code_sha256={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
  metrics={'source_checks':'provided evidence ID and time; at least one direct source per assessed enemy, other observed enemies allowed as context; not semantic entailment','sector_match':'reported focus matches the last observed geographic sector; not ground-truth tactical intent','response_axis':'selected screen_north/screen_south agrees with history','orders':'atomic batch acceptance by actual C++'},
  limitations='Assistant-designed controlled cases, no independent intent accuracy or win-rate claim. Token usage is recorded but not equalized; candidates are heuristic scaffolding common to all conditions. No model tuning after a verification run.')
 save(out/'protocol.json',protocol);records=[];engine=BattleProcess();paired={}
 try:
  for variant in protocol['variants']:
   for direction in ('north','south'):
    for mode in args.modes:
     memory=BattleMemory(':memory:')
     try:
      obs,frames=prepare(engine,direction,variant,memory)
      key=(variant,direction);paired[key]=dict(observation=digest(obs),proposals=digest(plans(obs)))
      context=memory.decision_context(obs,mode);save(out/f'v{variant}_{direction}_{mode}_input.json',dict(observation=obs,context=context))
      result=decide_context(obs,context,infer=functools.partial(chat,config=cfg))
      applied=engine.request(dict(command='step',ticks=0,expected_tick=obs['tick'],orders=result['orders'])) if result['grounding_passed'] else None
      assessments=result['model_response']['assessments']
      row=dict(variant=variant,direction=direction,mode=mode,current_digest=digest(obs),proposal_digest=digest(plans(obs)),grounding_passed=result['grounding_passed'],orders_accepted=bool(applied and applied['batch_accepted']),
       track_recovered=any(t['status']=='lost_contact' for t in context['tracks']),
       sector_match=bool(assessments) and all(a['focus_sector']==direction for a in assessments),response_axis_match=result['selected_plan']=='screen_'+direction,
       selected_plan=result['selected_plan'],seconds=result['seconds'],usage=result['usage'],warnings=result['calibration_warnings'])
      save(out/f'v{variant}_{direction}_{mode}_decision.json',result)
     except Exception as e:row=dict(variant=variant,direction=direction,mode=mode,error=str(e),orders_accepted=False)
     finally:memory.close()
     records.append(row)
     with (out/'records.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
     print(json.dumps(row,ensure_ascii=True),flush=True)
  groups={}
  for mode in args.modes:
   rows=[r for r in records if r['mode']==mode];groups[mode]=dict(calls=len(rows),errors=sum('error' in r for r in rows),grounded=sum(r.get('grounding_passed',False) for r in rows),orders_accepted=sum(r['orders_accepted'] for r in rows),recovered=sum(r.get('track_recovered',False) for r in rows),sector_match=sum(r.get('sector_match',False) for r in rows),response_axis_match=sum(r.get('response_axis_match',False) for r in rows))
  pairs=[dict(variant=v,same_current=paired.get((v,'north'),{}).get('observation')==paired.get((v,'south'),{}).get('observation'),same_proposals=paired.get((v,'north'),{}).get('proposals')==paired.get((v,'south'),{}).get('proposals')) for v in protocol['variants']]
  save(out/'summary.json',dict(groups=groups,pairs=pairs,records=records,limitations=protocol['limitations']))
  print('SAVED '+str(out),flush=True)
 finally:engine.close()
if __name__=='__main__':main()
