"""Controlled temporal-evidence cases, with hidden opponent orders for audit.

The two directions have identical current RED observations. Direction labels,
the hidden state and scripted orders are never part of the model input.
"""
import random

def case(direction,variant=0):
 if direction not in ('north','south'):raise ValueError('invalid direction')
 ids=[1,2,4,5,6,7];rng=random.Random(4100+variant)
 remap=dict(zip(ids,rng.sample(range(20,200),6))) if variant else dict(zip(ids,ids))
 positions=[(1,100,280,2),(2,260,280,2),(4,400,140,2),(5,540,80,1),(6,400,420,2),(7,540,490,1)]
 red1,red2,enemy=1+variant*1000,2+variant*1000,101+variant*1000
 nodes=[dict(id=remap[i],x=x*(1+.08*variant)+17*variant,y=y*(1+.06*variant)+11*variant,terrain=t) for i,x,y,t in positions]
 start=4 if direction=='north' else 6;end=5 if direction=='north' else 7
 cfg=dict(name='contact_trace_v4',nodes=nodes,edges=[[remap[a],remap[b],c] for a,b,c in [(1,2,4),(2,4,4),(4,5,2),(2,6,4),(6,7,2)]],
  units=[dict(id=red1,side='red',node=remap[1],role='infantry'),dict(id=red2,side='red',node=remap[2],role='infantry'),dict(id=enemy,side='blue',node=remap[start],role='light')],
  objectives=[dict(node=remap[4],name='通道甲'),dict(node=remap[6],name='通道乙')],horizon=150,score_limit=100)
 return cfg,dict(side='blue',unit_id=enemy,action='MOVE',target_node=remap[end])
