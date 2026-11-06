"""Real C++ mission episodes and optional local-model development probes.

No statistical win-rate or independent intent-accuracy claim is made.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
from battle_service import BattleProcess, ENGINE
from battle_memory import BattleMemory
from mission_scenarios import mission_scenario
from mission_planner import plans, scripted_decision
from mission_commander import decide_context

ROOT = Path(__file__).resolve().parent


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def temporal_case(direction):
    from commander_cases import case
    cfg, opening = case(direction)
    cfg['name'] = 'mission_temporal_probe_v5'
    cfg['units'][1]['role'] = 'light'
    cfg['nodes'] += [dict(id=8,x=750,y=80,terrain=2), dict(id=9,x=750,y=490,terrain=2)]
    cfg['nodes'] += [dict(id=10,x=480,y=110,terrain=2), dict(id=11,x=480,y=455,terrain=2)]
    cfg['edges'] = [e for e in cfg['edges'] if set(e[:2]) not in ({4,5},{6,7})]
    cfg['edges'] += [[4,10,1],[10,5,2],[6,11,1],[11,7,2]]
    cfg['edges'] += [[5,8,100],[7,9,100]]
    cfg['mission'] = dict(type='breakthrough',mover='blue',deadline=120,required=1,eligible_units=[101],
                          sites=[dict(id='A',node=8),dict(id='B',node=9)],
                          target_ids=['A' if direction=='north' else 'B'],target_public=False,
                          fallback_nodes=dict(red=[1],blue=[8,9]))
    return cfg, opening


def prepare(engine, direction, memory):
    cfg, opening = temporal_case(direction)
    engine.request(dict(command='reset',scenario=cfg))
    frames = []
    for tick in range(9):
        obs=engine.request(dict(command='state',side='red'));memory.observe(obs);frames.append(obs)
        if tick<8:engine.request(dict(command='step',ticks=1,orders=[opening] if tick==0 else []))
    return obs,frames


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model',action='store_true');ap.add_argument('--tag',default='development')
    args=ap.parse_args();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=ROOT/'results/mission_v5'/(args.tag+'_'+stamp);out.mkdir(parents=True)
    files=['mission_commander.py','mission_reasoning.py','mission_planner.py','mission_scenarios.py','battle_memory.py','run_mission_validation.py']
    protocol=dict(kind='mission_development_integration',timestamp_utc=stamp,
                  code_sha256={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
                  engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(), model_enabled=args.model,
                  max_output_tokens=1200,seed=42,temperature=0,
                  limitations='Assistant-designed small development cases. Stepwise integration, not real-time win-rate study. Input lengths differ; output caps/seeds equal and actual token usage recorded. Private goal labels kept only in evaluator output.')
    if args.model:
        from model_client import backend
        protocol['model']=backend()
    save(out/'protocol.json',protocol)
    engine=BattleProcess();summary=dict(baselines=[],temporal=[],closed_loop=[])
    try:
        for kind,target,swap in [('breakthrough','A',False),('breakthrough','A',True),('hidden','A',False),('hidden','B',False),('hidden','B',True),('hold_extract','A',False),('hold_extract','A',True)]:
            cfg=mission_scenario(kind,target,swap,rotate=swap);engine.request(dict(command='reset',scenario=cfg));frames=[];decisions=[]
            while True:
                state=engine.request(dict(command='state'));frames.append(state)
                if state['winner']:break
                orders=[]
                for side in ('red','blue'):
                    obs=engine.request(dict(command='state',side=side));d=scripted_decision(obs);orders.extend(d['orders']);decisions.append(dict(side=side,**d))
                applied=engine.request(dict(command='step',ticks=4,orders=orders))
                if not applied['batch_accepted']:raise RuntimeError(applied['order_checks'])
            label=f'{kind}_{target}_{"swap" if swap else "normal"}'
            save(out/(label+'.json'),dict(frames=frames,decisions=decisions))
            row=dict(case=label,tick=state['tick'],winner=state['winner'],reason=state['winner_reason'],exited=sum(u['status']=='EXITED' for u in state['entities']))
            summary['baselines'].append(row);print(json.dumps(row),flush=True)
        paired={}
        for direction in ('north','south'):
            memory=BattleMemory(':memory:')
            try:
                obs,frames=prepare(engine,direction,memory);paired[direction]=dict(current=digest(obs),proposals=digest(plans(obs)))
                save(out/(direction+'_observed_frames.json'),frames)
                for mode in ('current','memory'):
                    context=memory.decision_context(obs,mode);save(out/(direction+'_'+mode+'_input.json'),dict(observation=obs,context=context))
                    if not args.model:continue
                    d=decide_context(obs,context)
                    applied=engine.request(dict(command='step',ticks=0,expected_tick=obs['tick'],orders=d['orders'])) if d['grounding_passed'] else None
                    save(out/(direction+'_'+mode+'_decision.json'),d)
                    row=dict(case=direction,mode=mode,selected_plan=d['selected_plan'],goals=d['goal_hypotheses'],
                             grounding=d['grounding_passed'],orders_accepted=bool(applied and applied['batch_accepted']),seconds=d['seconds'],usage=d['usage'])
                    summary['temporal'].append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
            finally:memory.close()
        summary['paired']=dict(same_current=paired['north']['current']==paired['south']['current'],same_proposals=paired['north']['proposals']==paired['south']['proposals'])
        if not all(summary['paired'].values()):raise AssertionError('paired current/proposals differ')
        if args.model:
            engine.request(dict(command='reset',scenario=mission_scenario('hidden','B')));memory=BattleMemory(':memory:');previous=None
            try:
                for round_id in range(5):
                    obs=engine.request(dict(command='state',side='blue'));memory.observe(obs)
                    ctx=memory.decision_context(obs,'memory',previous);d=decide_context(obs,ctx,previous)
                    red=engine.request(dict(command='state',side='red'));rd=scripted_decision(red)
                    applied=engine.request(dict(command='step',ticks=0,expected_tick=obs['tick'],orders=rd['orders']+d['orders']))
                    d['accepted']=bool(d['grounding_passed'] and applied['batch_accepted']);d['side']='blue'
                    save(out/f'closed_loop_{round_id}.json',dict(observation=obs,context=ctx,decision=d))
                    row=dict(round=round_id,tick=obs['tick'],plan=d['selected_plan'],accepted=d['accepted'],seconds=d['seconds'],usage=d['usage'])
                    summary['closed_loop'].append(row);print(json.dumps(row),flush=True)
                    if d['accepted']:previous=d
                    for _ in range(8):
                        state=engine.request(dict(command='step',ticks=1));obs=engine.request(dict(command='state',side='blue'));memory.observe(obs)
                        if state['winner']:break
                    if state['winner']:break
            finally:memory.close()
        save(out/'summary.json',summary);print('SAVED '+str(out),flush=True)
    finally:engine.close()


if __name__=='__main__':main()
