import copy,json,unittest
from battle_service import BattleProcess
from battle_memory import BattleMemory
from battle_planner import plans,execution_feedback,triggers
from battle_commander import decide_context
from battle_scenarios import mechanism

def frame(tick,node=None,status='READY',side='red'):
 return dict(perspective=side,tick=tick,entities=[] if node is None else [dict(id=101,side='blue',role='light',current_node=node,status=status,hp=100)],nodes=[dict(id=1,x=0,y=0,terrain=2),dict(id=2,x=0,y=100,terrain=2)],visible_nodes=[1,2],objectives=[])

class TemporalMemory(unittest.TestCase):
 def setUp(self):self.m=BattleMemory(':memory:')
 def tearDown(self):self.m.close()
 def test_current_condition_cannot_see_past_contact(self):
  self.m.observe(frame(0,1));self.m.observe(frame(1,None));c=self.m.decision_context(frame(8,None),'current');self.assertEqual(c['tracks'],[]);self.assertEqual(c['evidence'],[])
 def test_retrieval_recovers_contact_outside_recent_window(self):
  self.m.observe(frame(0,1))
  for t in range(1,9):self.m.observe(frame(t,None))
  self.assertEqual(self.m.decision_context(frame(8,None),'recent')['tracks'],[])
  c=self.m.decision_context(frame(8,None),'memory');self.assertEqual(c['tracks'][0]['last_seen_node'],1);self.assertEqual(c['tracks'][0]['age'],8);self.assertTrue(c['tracks'][0]['last_location_cleared'])
 def test_future_and_other_side_do_not_change_context(self):
  self.m.observe(frame(0,1));a=self.m.decision_context(frame(4,None))
  self.m.observe(frame(30,2));other=frame(2,2,side='blue');other['entities'][0]['side']='red';self.m.observe(other)
  self.assertEqual(a,self.m.decision_context(frame(4,None)))
 def test_current_sighting_overrides_old_location(self):
  self.m.observe(frame(0,1));c=self.m.decision_context(frame(3,2));t=c['tracks'][0];self.assertEqual(t['last_seen_node'],2);self.assertEqual(t['age'],0);self.assertEqual(t['status'],'visible')
 def test_confirmed_destroyed_contact_never_resurrects_as_ghost(self):
  self.m.observe(frame(0,1));self.m.observe(frame(1,1,'DESTROYED'));self.m.observe(frame(2,None));self.assertEqual(self.m.last_contacts(frame(2,None)),[]);self.assertEqual(self.m.decision_context(frame(2,None))['tracks'][0]['status'],'confirmed_destroyed')
 def test_movement_trail_preserves_order(self):
  self.m.observe(frame(0,1));self.m.observe(frame(1,2));self.m.observe(frame(2,None));trail=self.m.decision_context(frame(3,None))['tracks'][0]['positions'];self.assertEqual(trail,[dict(tick=0,node=1),dict(tick=1,node=2)])

class JointPlanning(unittest.TestCase):
 def setUp(self):self.p=BattleProcess();self.m=BattleMemory(':memory:')
 def tearDown(self):self.p.close();self.m.close()
 def observation(self):return self.p.request(dict(command='state',side='red'))
 def test_all_default_joint_proposals_pass_actual_engine(self):
  obs=self.observation()
  for candidate in plans(obs):
   self.p.request(dict(command='reset'));s=self.p.request(dict(command='step',ticks=0,expected_tick=0,orders=candidate['orders']));self.assertTrue(s['batch_accepted'],candidate)
 def test_candidate_plans_do_not_depend_on_hidden_enemy(self):
  a=mechanism('plains');a['nodes'][2]['x']=5000
  # The default battlefield has no initially visible opposing units.
  obs=self.observation();self.assertFalse(any(u['side']=='blue' for u in obs['entities']));self.assertEqual(plans(obs),plans(copy.deepcopy(obs)))
 def test_artillery_support_plans_do_not_assault_objective(self):
  obs=self.observation();targets={o['node'] for o in obs['objectives']}
  for p in plans(obs):
   for a in p['assignments']:
    if a['role']=='artillery' and p['id'] not in ('withdraw','hold'):self.assertNotIn(a['target_node'],targets)
 def test_low_morale_proposals_retreat_instead_of_assault(self):
  obs=self.observation();own=next(u for u in obs['entities'] if u['side']=='red');own['morale']=30
  for p in plans(obs):
   a=next(a for a in p['assignments'] if a['unit_id']==own['id']);self.assertIn(a['action'],('RETREAT','DEFEND'))
 def test_no_contact_emits_no_invented_assessment(self):
  obs=self.observation();context=self.m.decision_context(obs)
  def infer(messages,**kw):
   self.assertEqual(kw['schema']['properties']['assessments']['maxItems'],0)
   return dict(text=json.dumps(dict(assessments=[],selected_plan='advance',choice_reason='先侦察争夺目标',reconsider_when=['new_contact'])),seconds=0)
  r=decide_context(obs,context,infer=infer);self.assertTrue(r['grounding_passed']);self.assertTrue(r['orders']);self.assertEqual(r['intent'],[])
 def test_unknown_citation_rejects_proposal(self):
  self.p.request(dict(command='reset',scenario=mechanism('front')));obs=self.observation();self.m.observe(obs);context=self.m.decision_context(obs)
  def infer(*args,**kw):return dict(text=json.dumps(dict(assessments=[dict(enemy_id=101,intent='assault',focus_sector='north',confidence='low',support=['FUTURE_FAKE'],counter_evidence=[],basis='test')],selected_plan='advance',choice_reason='test',reconsider_when=['periodic'])))
  r=decide_context(obs,context,infer=infer);self.assertFalse(r['grounding_passed']);self.assertEqual(r['orders'],[])
 def test_feedback_uses_real_loss_and_control_state(self):
  self.p.request(dict(command='reset',scenario=mechanism('front')));obs=self.observation();previous=dict(selected_plan='hold',source_tick=0,orders=[dict(unit_id=1,target_node=1)],friendly_at_issue={'1':dict(hp=100)})
  self.p.request(dict(command='step',ticks=2));feedback=execution_feedback(self.observation(),previous);self.assertGreater(feedback['units'][0]['hp_loss'],0)
 def contextual_result(self,support):
  cfg=mechanism('front');cfg['units'].append(dict(id=102,side='blue',node=3,role='tank'));self.p.request(dict(command='reset',scenario=cfg));obs=self.observation();self.m.observe(obs)
  def infer(*args,**kw):return dict(text=json.dumps(dict(assessments=[dict(enemy_id=101,intent='assault',focus_sector='north',confidence='low',support=support,counter_evidence=[],basis='两支敌军协同活动')],selected_plan='advance',choice_reason='test',reconsider_when=['periodic'])))
  return decide_context(obs,self.m.decision_context(obs),infer=infer)
 def test_direct_plus_observed_neighbor_evidence_is_allowed(self):
  r=self.contextual_result(['F0U101','F0U102']);self.assertTrue(r['grounding_passed']);self.assertTrue(any(e['usage']=='observed_context' for e in r['evidence_checks']))
 def test_other_unit_evidence_alone_cannot_support_assessed_unit(self):
  r=self.contextual_result(['F0U102']);self.assertFalse(r['grounding_passed']);self.assertIn('no_direct_evidence_for_assessed_unit',r['grounding_errors'])
 def test_new_opposite_side_observation_revises_prior_hypothesis(self):
  self.p.request(dict(command='reset',scenario=mechanism('front')));obs=self.observation();self.m.observe(obs);context=self.m.decision_context(obs)
  context['tracks'][0]['sector']='south'
  previous=dict(source_tick=-1,selected_plan='hold',orders=[],intent=[dict(enemy_id=101,focus_sector='north',hypothesis='北侧机动',confidence='low')])
  def infer(messages,**kw):
   payload=json.loads(messages[1]['content']);self.assertIn('另一侧',payload['previous_plan_feedback']['hypothesis_updates'][0]['update'])
   return dict(text=json.dumps(dict(assessments=[dict(enemy_id=101,intent='unknown',focus_sector='south',confidence='low',support=['F0U101'],counter_evidence=[],basis='新目击')],selected_plan='advance',choice_reason='test',reconsider_when=['new_contact'])))
  self.assertTrue(decide_context(obs,context,previous,infer)['grounding_passed'])
 def test_new_contact_triggers_replanning(self):
  before=self.observation();after=copy.deepcopy(before);after['entities'].append(dict(id=101,side='blue',status='READY'));self.assertIn('new_contact',triggers(after,before))

if __name__=='__main__':unittest.main(verbosity=2)
