"""Small inspectable mechanism scenarios alongside the full 24-node match."""
def mechanism(name):
 nodes=[dict(id=1,x=230,y=260,terrain=2),dict(id=2,x=470,y=260,terrain=2),
        dict(id=3,x=710,y=260,terrain=2),dict(id=4,x=230,y=440,terrain=1),
        dict(id=5,x=470,y=440,terrain=0),dict(id=6,x=710,y=440,terrain=3)]
 edges=[[1,2,5],[2,3,5],[1,4,4],[4,5,5],[5,6,5],[3,6,4],[2,5,4]]
 units=[dict(id=1,side='red',node=1,role='infantry'),dict(id=2,side='red',node=1,role='infantry'),dict(id=101,side='blue',node=2,role='infantry')]
 if name=='flank':units[1]['node']=3
 if name=='morale':units[2].update(morale=25);units[1]['node']=3
 if name=='forest':
  nodes[0]['terrain']=1
  nodes[1]['terrain']=1
  units=[dict(id=1,side='red',node=1,role='tank'),dict(id=101,side='blue',node=2,role='infantry')]
 if name=='plains':units=[dict(id=1,side='red',node=1,role='tank'),dict(id=101,side='blue',node=2,role='infantry')]
 if name not in ('front','flank','morale','forest','plains'):raise ValueError('unknown_scenario')
 return dict(name=name+'_mechanism_v3',nodes=nodes,edges=edges,units=units,objectives=[dict(node=2,name='中央阵地')],horizon=160,score_limit=100)
