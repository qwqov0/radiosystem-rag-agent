"""In-process HTTP contracts with the real C++ service, no model or network."""
import unittest
import battle_api
from fastapi.testclient import TestClient


class MissionAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(battle_api.app);cls.client=cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):cls.context.__exit__(None,None,None)
    def test_health_and_new_default(self):
        self.assertEqual(self.client.get('/health').json()['rules'],'battle_v5.0')
        self.client.post('/api/battle/reset',json={'scenario':'hidden'})
        self.assertEqual(self.client.get('/api/battle/state?side=blue').json()['state']['own_mission']['kind'],'deny')
    def test_side_contract_and_replay_hide_private_goal(self):
        self.client.post('/api/battle/reset',json={'scenario':'hidden'})
        state=self.client.get('/api/battle/state?side=blue').json()['state']
        self.assertNotIn('mission_details',state);self.assertNotIn('missions',state)
        self.assertEqual(len(state['own_mission']['targets']),2)
        self.assertIsNone(state['own_mission']['completed'])
        frames=self.client.get('/api/battle/replay?side=blue').json()['frames']
        self.assertTrue(all(f['perspective']=='blue' and 'mission_details' not in f for f in frames))
    def test_swap_and_rotation(self):
        state=self.client.post('/api/battle/reset',json={'scenario':'breakthrough','swap_sides':True,'rotate':True}).json()['state']
        self.assertEqual(state['mission_details']['mover'],'blue')
        own=self.client.get('/api/battle/state?side=blue').json()['state']['own_mission']
        self.assertEqual(own['kind'],'breakthrough');self.assertEqual(own['eligible_units'],[1,2,3,4])
    def test_scripts_and_page_are_served(self):
        page=self.client.get('/').text
        self.assertIn('/assets/battle_mission_v5.js',page);self.assertIn("EXITED:'已脱离'",page)
        script=self.client.get('/assets/battle_mission_v5.js')
        self.assertEqual(script.status_code,200);self.assertIn('后续观察',script.text)
    def test_unknown_scene_is_rejected(self):
        self.assertEqual(self.client.post('/api/battle/reset',json={'scenario':'no_such_scene'}).status_code,400)


if __name__=='__main__':unittest.main(verbosity=2)
