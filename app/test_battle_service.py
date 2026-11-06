"""Real C++ coordinator concurrency checks; model calls are controlled stubs."""
import threading,time,unittest
from unittest.mock import patch
from battle_service import BattleService

class Runtime(unittest.TestCase):
 def setUp(self):self.s=BattleService();self.s.configure(controllers={'red':'memory','blue':'manual'});self.entered=threading.Event();self.release=threading.Event()
 def tearDown(self):self.release.set();self.wait();self.s.close()
 def wait(self):
  end=time.monotonic()+3
  while self.s.busy['red'] and time.monotonic()<end:time.sleep(.01)
 def fake(self,obs,memory,mode):
  self.entered.set();self.release.wait(3)
  return dict(orders=[],intent=[],plan='controlled test',reconsider_when='test',evidence=[],controller=mode,source_tick=obs['tick'])
 def test_simulation_advances_while_model_is_busy(self):
  with patch('battle_service.decide',self.fake):
   self.s.request_decision('red');self.assertTrue(self.entered.wait(1));self.assertTrue(self.s.busy['red']);self.s.step(2);self.assertEqual(self.s.state['tick'],2);self.release.set();self.wait();self.assertTrue(self.s.traces[-1]['accepted'])
 def test_expired_decision_is_not_executed(self):
  with patch('battle_service.decide',self.fake):
   self.s.request_decision('red');self.assertTrue(self.entered.wait(1));self.s.step(17);self.release.set();self.wait();self.assertEqual(self.s.traces[-1]['error'],'expired_decision')
 def test_reset_discards_previous_match_job(self):
  with patch('battle_service.decide',self.fake):
   old=self.s.match_id;self.s.request_decision('red');self.assertTrue(self.entered.wait(1));self.s.reset();self.release.set();time.sleep(.05);self.assertNotEqual(old,self.s.match_id);self.assertEqual(self.s.traces,[]);self.assertEqual(self.s.state['tick'],0)
 def test_side_view_never_includes_opponent_decisions(self):
  self.s.traces=[dict(side='red',plan='red private'),dict(side='blue',plan='blue private')]
  self.assertEqual([d['side'] for d in self.s.view('red')['decisions']],['red'])
 def test_ungrounded_proposal_is_never_sent_to_engine(self):
  def ungrounded(obs,memory,mode):
   return dict(orders=[dict(side='red',unit_id=1,action='MOVE',target_node=8)],intent=[],plan='test',controller=mode,source_tick=obs['tick'],grounding_passed=False)
  with patch('battle_service.decide',ungrounded):
   self.s.request_decision('red');self.wait();self.assertEqual(self.s.traces[-1]['error'],'grounding_rejected');self.assertEqual(self.s.state['tick'],0);self.assertEqual(next(u for u in self.s.state['entities'] if u['id']==1)['route'],[])
 def test_job_gets_previous_accepted_plan_and_frozen_context(self):
  self.s.traces=[dict(side='red',accepted=True,selected_plan='advance',orders=[],source_tick=0)]
  seen=[]
  def inspect(obs,memory,mode):
   seen.append((memory.previous_plan['selected_plan'],memory.decision_context(obs,mode)['query']['as_of_tick']))
   return dict(orders=[],intent=[],plan='test',controller=mode,source_tick=obs['tick'])
  with patch('battle_service.decide',inspect):self.s.request_decision('red');self.wait()
  self.assertEqual(seen,[('advance',0)])
if __name__=='__main__':unittest.main(verbosity=2)
