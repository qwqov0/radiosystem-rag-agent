from agent import Decision,validate_decision,encode,PacketBuffer,JsonLines
import json,unittest
STATE={'tick':10,'nodes':[{'id':1},{'id':2},{'id':3},{'id':4}],'edges':[[1,2,1],[2,3,1]],'entities':[{'id':11,'side':'red','current_node':1,'state':5,'hp':100},{'id':12,'side':'blue','current_node':2,'state':5,'hp':100},{'id':13,'side':'red','current_node':1,'state':6,'hp':0}]}
def make(**kw):
 d=dict(tick=10,unit_id=11,action='DEFEND',target_node=1,evidence=['r1'],reason='test');d.update(kw);return Decision(**d)
class Guards(unittest.TestCase):
 def test_valid(self):self.assertEqual(validate_decision(make(),STATE,'red',{'r1'}),[])
 def test_stale(self):self.assertIn('stale_snapshot',validate_decision(make(tick=9),STATE,'red',{'r1'}))
 def test_owner(self):self.assertIn('foreign_unit',validate_decision(make(unit_id=12,target_node=2),STATE,'red',{'r1'}))
 def test_dead(self):self.assertIn('unit_uncontrollable',validate_decision(make(unit_id=13),STATE,'red',{'r1'}))
 def test_evidence(self):self.assertIn('unknown_evidence',validate_decision(make(evidence=['fake']),STATE,'red',{'r1'}))
 def test_unknown_unit(self):self.assertIn('unknown_unit',validate_decision(make(unit_id=99),STATE,'red',{'r1'}))
 def test_unknown_target(self):self.assertIn('unknown_node',validate_decision(make(target_node=99),STATE,'red',{'r1'}))
 def test_defend_here(self):self.assertIn('defend_not_current_node',validate_decision(make(target_node=2),STATE,'red',{'r1'}))
 def test_move_reachable(self):self.assertEqual(validate_decision(make(action='MOVE',target_node=3),STATE,'red',{'r1'}),[])
 def test_move_disconnected(self):self.assertIn('unreachable_node',validate_decision(make(action='MOVE',target_node=4),STATE,'red',{'r1'}))
 def test_retreat_adjacent(self):self.assertIn('nonadjacent_action',validate_decision(make(action='RETREAT',target_node=3),STATE,'red',{'r1'}))
 def test_wait_no_packet(self):self.assertEqual(encode(make(action='WAIT')),b'')
 def test_packet_size(self):self.assertEqual(len(encode(make())),40)
 def test_binary_fragmentation(self):
  p=encode(make());b=PacketBuffer();self.assertEqual(b.feed(p[:7]),[]);self.assertEqual(b.feed(p[7:]+p+p[:11]),[p,p]);self.assertEqual(b.feed(p[11:]),[p])
 def test_unicode_fragmentation(self):
  raw=(json.dumps({'type':'测试','tick':10},ensure_ascii=False)+'\n').encode();p=JsonLines();out=[]
  for b in raw:out.extend(p.feed(bytes([b])))
  self.assertEqual(out,[{'type':'测试','tick':10}])
 def test_extra_key(self):
  with self.assertRaises(Exception):Decision(**dict(tick=1,unit_id=11,action='MOVE',target_node=2,evidence=[],reason='',execute_shell='bad'))
 def test_unknown_action(self):
  with self.assertRaises(Exception):make(action='SHELL')
 def test_uint32_overflow(self):
  with self.assertRaises(Exception):make(unit_id=4294967296)
 def test_boolean_tick(self):
  with self.assertRaises(Exception):make(tick=True)
if __name__=='__main__':unittest.main(verbosity=2)
