import unittest,struct
from engine_adapter import CppSession,observe
from agent_v2 import candidates
def packet(tick=0,unit=1,cmd=1,target=2):return struct.pack('<QIIB7sI12s',tick,0,unit,cmd,b'\0'*7,target,b'\0'*12).hex()
class Integration(unittest.TestCase):
 def setUp(self):self.engine=CppSession();self.initial=self.engine.request({'command':'reset'})
 def tearDown(self):self.engine.close()
 def check_order(self,data):return self.engine.request(dict(command='step',ticks=1,orders=[data]))['order_checks'][0]
 def test_actual_move(self):
  end=self.engine.request(dict(command='step',ticks=4,orders=[dict(side='red',packet_hex=packet())]));red=next(u for u in end['entities'] if u['side']=='red');self.assertEqual(red['current_node'],2);self.assertTrue(end['order_checks'][0]['accepted'])
 def test_stale(self):self.assertEqual(self.check_order(dict(side='red',packet_hex=packet(tick=999)))['error'],'stale_snapshot')
 def test_foreign(self):self.assertEqual(self.check_order(dict(side='red',packet_hex=packet(unit=74)))['error'],'foreign_unit')
 def test_node(self):self.assertEqual(self.check_order(dict(side='red',packet_hex=packet(target=999)))['error'],'unknown_node')
 def test_action(self):self.assertEqual(self.check_order(dict(side='red',packet_hex=packet(cmd=255)))['error'],'unknown_action')
 def test_nonadjacent(self):self.assertEqual(self.check_order(dict(side='red',packet_hex=packet(cmd=2,target=4)))['error'],'nonadjacent_action')
 def test_defend(self):self.assertEqual(self.check_order(dict(side='red',packet_hex=packet(cmd=3,target=2)))['error'],'defend_not_current_node')
 def test_hex(self):self.assertEqual(self.check_order(dict(side='red',packet_hex='gg'*40))['error'],'packet_hex')
 def test_duplicate(self):
  r=self.engine.request(dict(command='step',ticks=1,orders=[dict(side='red',packet_hex=packet()),dict(side='red',packet_hex=packet())]));self.assertEqual(r['order_checks'][1]['error'],'duplicate_order')
 def test_hidden_enemy(self):
  obs=observe(self.initial,'red');self.assertEqual([u['id'] for u in obs['entities']],[1]);self.assertNotIn(5,obs['visible_nodes']);self.assertNotIn('control_ticks',obs)
 def test_candidates_ownership(self):
  c=candidates(observe(self.initial,'red'),'red');self.assertTrue(all(v['unit_id'] in [0,1] for v in c.values()));self.assertNotIn('1:ATTACK:4',c)
 def test_replay_deterministic(self):
  req=dict(command='step',ticks=8,orders=[dict(side='red',packet_hex=packet(target=3)),dict(side='blue',packet_hex=packet(unit=74,target=3))]);a=self.engine.request(req);self.engine.request({'command':'reset'});b=self.engine.request(req);self.assertEqual(a,b)
if __name__=='__main__':unittest.main()
