import unittest
from rag_v2 import check_quotes
class Quotes(unittest.TestCase):
 def setUp(self):self.rows=[dict(id='example:L1-5',status='source_snapshot_not_runtime_proof',text='12: return std::sqrt(dx * dx + dy * dy);')]
 def test_quote(self):self.assertTrue(check_quotes({'citations':[dict(source_id='S1',quote='std::sqrt(dx * dx + dy * dy)')]},self.rows)[0]['valid'])
 def test_whitespace(self):self.assertTrue(check_quotes({'citations':[dict(source_id='S1',quote='std::sqrt(dx*dx +dy*dy)')]},self.rows)[0]['valid'])
 def test_invented_quote(self):self.assertFalse(check_quotes({'citations':[dict(source_id='S1',quote='return 9999;')]},self.rows)[0]['valid'])
 def test_wrong_source(self):self.assertFalse(check_quotes({'citations':[dict(source_id='S2',quote='std::sqrt')]},self.rows)[0]['valid'])
 def test_tiny_quote(self):self.assertFalse(check_quotes({'citations':[dict(source_id='S1',quote='dx')]},self.rows)[0]['valid'])
if __name__=='__main__':unittest.main()
