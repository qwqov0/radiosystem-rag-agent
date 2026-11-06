"""Behavioral regression checks against the compiled authoritative C++ engine."""
from pathlib import Path
import copy, json, tempfile, unittest
from battle_service import BattleProcess
from battle_memory import BattleMemory
from battle_scenarios import mechanism

def unit(state,uid):return next(u for u in state['entities'] if u['id']==uid)
def config(nodes,edges,units,objectives=None):
 return dict(name='test',nodes=[dict(id=i,x=x,y=y,terrain=t) for i,x,y,t in nodes],edges=edges,units=units,objectives=objectives or [],horizon=500,score_limit=300)
def u(uid,side,node,role='infantry',**kw):return dict(id=uid,side=side,node=node,role=role,**kw)
def order(uid,node,action='MOVE',side='red'):return dict(unit_id=uid,target_node=node,action=action,side=side)

class EngineRules(unittest.TestCase):
 def setUp(self):self.p=BattleProcess()
 def tearDown(self):self.p.close()
 def reset(self,cfg):return self.p.request(dict(command='reset',scenario=cfg))
 def step(self,ticks=1,orders=None,expected_tick=None):
  r=dict(command='step',ticks=ticks,orders=orders or [])
  if expected_tick is not None:r['expected_tick']=expected_tick
  return self.p.request(r)
 def test_default_has_tactical_map_and_four_roles(self):
  s=self.p.request(dict(command='state'));self.assertEqual(len(s['nodes']),24);self.assertEqual(len(s['entities']),10);self.assertEqual({u['role'] for u in s['entities']},{'infantry','light','tank','artillery'})
 def test_weighted_path_uses_lower_cost_not_fewer_edges(self):
  self.reset(config([(1,0,0,2),(2,1,1,2),(3,2,1,2),(4,3,0,2),(5,4,0,2)],[[1,4,40],[1,2,2],[2,3,2],[3,4,2],[4,5,10]],[u(1,'red',1),u(101,'blue',5)]))
  s=self.step(0,[order(1,4)]);self.assertEqual(unit(s,1)['route'],[2,3,4])
 def test_move_progress_and_identical_reissue(self):
  self.reset(mechanism('front'));a=self.step(2,[order(1,4)]);progress=unit(a,1)['progress'];b=self.step(0,[order(1,4)]);self.assertEqual(unit(b,1)['progress'],progress);self.assertGreater(progress,0)
 def test_flank_differs_from_same_front(self):
  self.reset(mechanism('front'));a=unit(self.step(),101)
  self.reset(mechanism('flank'));b=unit(self.step(),101)
  self.assertFalse(a['flanked']);self.assertTrue(b['flanked']);self.assertLess(b['hp'],a['hp']);self.assertLess(b['morale'],a['morale'])
 def test_ammo_zero_produces_no_fire(self):
  c=mechanism('front');c['units'][0]['ammo']=0;c['units'][1]['ammo']=0;self.reset(c);s=self.step();self.assertEqual(unit(s,101)['hp'],100);self.assertFalse(any(e['kind']=='fire' and e['actor'] in (1,2) for e in s['events']))
 def test_terrain_reverses_tank_infantry_trade(self):
  self.reset(mechanism('plains'));a=self.step(3)
  self.reset(mechanism('forest'));b=self.step(3)
  self.assertLess(unit(a,101)['hp'],unit(b,101)['hp']);self.assertGreater(unit(a,1)['hp'],unit(b,1)['hp'])
  self.assertGreater(unit(a,1)['hp'],unit(a,101)['hp']);self.assertLess(unit(b,1)['hp'],unit(b,101)['hp'])
 def test_light_moves_through_forest_faster_than_tank(self):
  c=config([(1,0,0,2),(2,100,0,1),(3,1000,0,2)],[[1,2,4],[2,3,40]],[u(1,'red',1,'light'),u(2,'red',1,'tank'),u(101,'blue',3)])
  self.reset(c);s=self.step(3,[order(1,2),order(2,2)]);self.assertEqual(unit(s,1)['current_node'],2);self.assertEqual(unit(s,2)['current_node'],1)
 def test_artillery_requires_current_friendly_spotting(self):
  c=config([(1,0,0,2),(2,100,0,2),(3,200,0,2),(4,300,0,2),(5,400,0,2)],[[1,2,4],[2,3,4],[3,4,4],[4,5,4]],[u(1,'red',1,'artillery'),u(101,'blue',4)])
  self.reset(c);a=self.step();self.assertEqual(unit(a,101)['hp'],100)
  c['units'].append(u(2,'red',2,'light'));self.reset(c);b=self.step();self.assertLess(unit(b,101)['hp'],100)
 def test_simultaneous_fire_does_not_cancel_destroyed_attacker(self):
  c=mechanism('plains');c['units'][0]['hp']=.1;c['units'][1]['hp']=.1;self.reset(c);s=self.step();self.assertEqual(unit(s,1)['status'],'DESTROYED');self.assertEqual(unit(s,101)['status'],'DESTROYED')
 def test_suppressive_fire_lowers_morale_and_causes_rout(self):
  self.reset(mechanism('morale'));s=self.step(3);self.assertTrue(any(e['kind']=='routed' and e['actor']==101 for e in s['events']));self.assertIn(unit(s,101)['status'],['ROUTED','SURRENDERED','DESTROYED'])
 def test_routed_units_reject_orders(self):
  self.reset(mechanism('morale'));s=self.step(2);s=self.step(0,[order(101,2,'DEFEND','blue')]);self.assertFalse(s['batch_accepted']);self.assertEqual(s['order_checks'][0]['error'],'unit_uncontrollable')
 def test_retreat_does_not_choose_enemy_occupied_first_neighbor(self):
  c=config([(1,0,0,2),(2,100,0,2),(3,100,100,1),(4,200,0,2)],[[2,1,4],[2,3,4],[2,4,4]],[u(1,'red',2,morale=20),u(101,'blue',1),u(102,'blue',4)])
  self.reset(c);s=self.step(2);self.assertEqual(unit(s,1)['route'],[3]);self.assertEqual(unit(s,1)['status'],'ROUTED')
 def test_morale_recovers_after_quiet_rally_period(self):
  c=config([(1,0,0,2),(2,100,0,1),(3,900,0,2),(4,1000,0,2)],[[1,2,1],[2,3,40],[3,4,1]],[u(1,'red',1,morale=21),u(101,'blue',4)])
  self.reset(c);s=self.step(0,[order(1,2,'RETREAT')]);self.assertTrue(s['batch_accepted']);s=self.step(16);self.assertEqual(unit(s,1)['status'],'READY');self.assertGreaterEqual(unit(s,1)['morale'],40)
 def test_fog_hides_orders_ammo_and_enemy_memory(self):
  self.reset(mechanism('front'));obs=self.p.request(dict(command='state',side='red'));e=unit(obs,101);self.assertNotIn('order',e);self.assertNotIn('route',e);self.assertNotIn('ammo',e);self.assertNotIn('morale',e);self.assertNotIn('score',obs)
 def test_terrain_occludes_visibility(self):
  c=config([(1,0,0,2),(2,100,0,1),(3,200,0,2)],[[1,2,4],[2,3,4]],[u(1,'red',1,'light'),u(101,'blue',3)])
  self.reset(c);s=self.p.request(dict(command='state',side='red'));self.assertNotIn(101,[u['id'] for u in s['entities']])
 def test_atomic_batch_ownership_and_duplicate(self):
  self.reset(mechanism('front'));s=self.step(0,[order(1,4),order(101,3)]);self.assertFalse(s['batch_accepted']);self.assertEqual(unit(s,1)['route'],[])
  s=self.step(0,[order(1,4),order(1,2)]);self.assertEqual(s['order_checks'][1]['error'],'duplicate_order')
 def test_stale_submission_cannot_advance_match(self):
  s=self.step(2,[order(1,2)],expected_tick=999);self.assertEqual(s['tick'],0);self.assertFalse(s['batch_accepted'])
 def test_invalid_reset_preserves_match(self):
  a=self.step(2);bad=mechanism('front');bad['edges'][0][2]=-1
  with self.assertRaises(ValueError):self.reset(bad)
  self.assertEqual(self.p.request(dict(command='state')), {k:v for k,v in a.items() if k not in ('order_checks','batch_accepted')})
 def test_replay_is_deterministic(self):
  c=mechanism('flank');self.reset(c);a=self.step(7);self.reset(c);self.assertEqual(a,self.step(7))
 def test_win_condition_finishes_and_freezes(self):
  c=mechanism('front');c['horizon']=3;self.reset(c);s=self.step(5);self.assertTrue(s['winner']);self.assertEqual(s['tick'],3);self.assertEqual(self.step(3)['tick'],3)

class MemoryIsolation(unittest.TestCase):
 def setUp(self):self.m=BattleMemory(':memory:')
 def tearDown(self):self.m.close()
 def frame(self,side,tick,enemies):return dict(perspective=side,tick=tick,entities=[dict(id=i,side='blue' if side=='red' else 'red',role='light',current_node=n,hp=100,status='READY') for i,n in enemies])
 def test_opponent_and_future_never_enter_retrieval(self):
  self.m.observe(self.frame('red',1,[(101,1)]));self.m.observe(self.frame('blue',2,[(777,8)]));self.m.observe(self.frame('red',20,[(101,9)]))
  r=self.m.retrieve(self.frame('red',5,[(101,1)]));self.assertTrue(r);self.assertTrue(all(e['tick']<5 for e in r));self.assertNotIn('777',json.dumps(r));self.assertNotIn('移动到9',json.dumps(r,ensure_ascii=False))
 def test_lost_contact_is_unknown_not_confirmed_retreat(self):
  self.m.observe(self.frame('red',1,[(101,1)]));self.m.observe(self.frame('red',2,[]));r=self.m.retrieve(self.frame('red',3,[]));self.assertTrue(any(e['kind']=='lost_contact' and '去向未知' in e['text'] for e in r))
 def test_same_present_different_history_returns_different_evidence(self):
  self.m.observe(self.frame('red',1,[(101,1)]));self.m.observe(self.frame('red',2,[(101,2)]));self.m.observe(self.frame('red',3,[]));a=self.m.retrieve(self.frame('red',4,[]))
  other=BattleMemory(':memory:')
  try:
   other.observe(self.frame('red',1,[(101,8)]));other.observe(self.frame('red',2,[(101,7)]));other.observe(self.frame('red',3,[]));b=other.retrieve(self.frame('red',4,[]));self.assertNotEqual([e['text'] for e in a],[e['text'] for e in b])
  finally:other.close()
 def test_observer_input_is_rejected(self):
  with self.assertRaises(ValueError):self.m.observe(self.frame('observer',1,[]))

if __name__=='__main__':unittest.main(verbosity=2)
