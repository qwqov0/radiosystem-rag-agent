"""Mission scenarios. Private choices belong to the engine, never model metadata."""
from secrets import choice

def mission_scenario(kind='breakthrough', target=None, swap_sides=False, rotate=False):
 if kind not in ('breakthrough','hidden','hold_extract'):raise ValueError('unknown mission scenario')
 target=target or (choice(['A','B']) if kind=='hidden' else 'A')
 if target not in ('A','B'):raise ValueError('invalid mission target')
 terrain=[1,1,2,3,1,1,2,0,3,2,0,2,1,1,2,0,1,1,2,2,3,2,2,2]
 nodes=[];edges=[]
 for r in range(4):
  for c in range(6):
   n=r*6+c+1;nodes.append(dict(id=n,x=85+c*145+(r%2)*22,y=85+r*125+(c%2)*12,terrain=terrain[n-1]))
   if c<5:edges.append([n,n+1,4.0])
   if r<3:edges.append([n,n+6,4.6])
 edges.extend([[9,16,5.8],[10,15,5.8]])
 roles=['infantry','infantry','light','tank','artillery']
 red=[7,19,1,13,1] if kind!='hold_extract' else [9,8,14,15,1]
 blue=[11,17,5,23,6]
 units=[dict(id=i+1,side='red',node=n,role=roles[i]) for i,n in enumerate(red)]
 units += [dict(id=i+101,side='blue',node=n,role=roles[i]) for i,n in enumerate(blue)]
 sites=[dict(id='A',node=12,name='A 东北出口'),dict(id='B',node=24,name='B 东南出口')]
 if kind=='hold_extract':sites=[dict(id='A',node=1,name='A 后方撤离区'),dict(id='B',node=19,name='B 备用撤离区')]
 mission=dict(type='hold_extract' if kind=='hold_extract' else 'breakthrough',mover='red',deadline=110 if kind=='hold_extract' else 100,
  required=2,eligible_units=[1,2,3,4],sites=sites,target_ids=[target],target_public=kind!='hidden',fallback_nodes={'red':[1,7,19],'blue':[6,12,24]})
 if kind=='hold_extract':mission.update(hold_until=32,hold_node=9)
 if swap_sides:
  for u in units:u['side']='blue' if u['side']=='red' else 'red'
  mission['mover']='blue';mission['fallback_nodes']={'blue':[1,7,19],'red':[6,12,24]}
 if rotate:
  for n in nodes:n['x']=920-n['x'];n['y']=560-n['y']
 # Hidden A/B use exactly the same public scene name and initial deployment.
 return dict(name='mission_hidden_v5' if kind=='hidden' else 'mission_'+kind+'_v5',nodes=nodes,edges=edges,units=units,
  objectives=[dict(node=9,name='北岭观察所'),dict(node=16,name='南部枢纽镇')],horizon=mission['deadline'],score_limit=9999,mission=mission)
