"""Authoritative mission boundaries, information isolation and reasoning guards."""
import copy
import json
import unittest
from battle_service import BattleProcess
from battle_memory import BattleMemory
from battle_planner import triggers
from mission_scenarios import mission_scenario
from mission_planner import plans, scripted_decision
from mission_commander import decide_context
from test_battle_v3 import config, u, unit, order


def tiny(required=1, deadline=5, start=1):
    c = config([(i, i*50, 0, 2) for i in range(1, 8)], [[i,i+1,1 if i==1 else 30] for i in range(1,7)],
               [u(1,'red',start,ammo=0), u(2,'red',1,ammo=0), u(101,'blue',7,ammo=0)])
    c['mission'] = dict(type='breakthrough',mover='red',deadline=deadline,required=required,
                        sites=[dict(id='A',node=2),dict(id='B',node=3)],target_ids=['A'],eligible_units=[1,2],target_public=False)
    return c


class MissionEngine(unittest.TestCase):
    def setUp(self): self.p=BattleProcess()
    def tearDown(self): self.p.close()
    def reset(self,c): return self.p.request(dict(command='reset',scenario=c))
    def obs(self,side='red'): return self.p.request(dict(command='state',side=side))
    def step(self,ticks=1,orders=None): return self.p.request(dict(command='step',ticks=ticks,orders=orders or []))
    def test_exact_deadline_success_precedes_timeout(self):
        self.reset(tiny(deadline=1));s=self.step(1,[order(1,2)])
        self.assertEqual((s['winner'],s['winner_reason'],s['tick']),('red','mission_completed',1))
    def test_timeout_does_not_award_kills_or_objective_score(self):
        c=tiny(deadline=2);c['objectives']=[dict(node=1,name='score')];c['score_limit']=1
        self.reset(c);s=self.step(3)
        self.assertEqual((s['winner'],s['winner_reason'],s['tick']),('blue','mission_deadline',2))
        self.assertGreater(s['score']['red'],s['score']['blue'])
    def test_exited_cannot_repeat_count_or_receive_commands(self):
        self.reset(tiny(required=2));self.step(1,[order(1,2)])
        self.assertEqual(self.obs()['own_mission']['completed'],1)
        s=self.step(0,[order(1,1)]);self.assertFalse(s['batch_accepted'])
        self.step(2);self.assertEqual(self.obs()['own_mission']['completed'],1)
        self.assertEqual(unit(self.obs(),1)['status'],'EXITED')
    def test_wrong_exit_and_ineligible_unit_do_not_count(self):
        c=tiny();c['mission']['eligible_units']=[1];c['units'][1]['node']=2
        self.reset(c);self.step(1,[order(1,3)])
        self.assertEqual(self.obs()['own_mission']['completed'],0)
        self.assertNotEqual(unit(self.obs(),2)['status'],'EXITED')
    def test_rout_on_exit_is_not_success(self):
        c=tiny(start=2);c['units'][0]['morale']=0
        self.reset(c);self.step();self.assertEqual(self.obs()['own_mission']['completed'],0)
    def test_combat_death_precedes_exit_and_impossible_mission_ends(self):
        c=tiny(start=2);c['units'][0].update(hp=.1,ammo=90);c['units'][2].update(node=2,ammo=90)
        c['mission']['eligible_units']=[1]
        self.reset(c);s=self.step();self.assertEqual(unit(s,1)['status'],'DESTROYED')
        self.assertEqual(s['winner_reason'],'mission_unachievable')
    def test_enemy_on_exit_prevents_uncontested_escape(self):
        c=tiny(start=2);c['units'][2]['node']=2
        self.reset(c);self.step();self.assertEqual(self.obs()['own_mission']['completed'],0)
    def test_last_remaining_friendly_exit_is_a_win(self):
        c=tiny(start=2);c['units']=[c['units'][0]];c['mission']['eligible_units']=[1]
        self.reset(c);s=self.step();self.assertEqual((s['winner'],s['winner_reason']),('red','mission_completed'))
    def test_private_target_indistinguishable_for_defender(self):
        self.reset(mission_scenario('hidden','A'));a=self.obs('blue');self.reset(mission_scenario('hidden','B'));b=self.obs('blue')
        self.assertEqual(a,b);self.assertNotIn('mission_details',a)
        self.assertEqual([s['id'] for s in a['own_mission']['targets']],['A','B'])
        self.assertIsNone(a['own_mission']['completed'])
    def test_mover_knows_own_target_observer_knows_both(self):
        self.reset(mission_scenario('hidden','B'))
        self.assertEqual([s['id'] for s in self.obs()['own_mission']['targets']],['B'])
        self.assertEqual(self.obs('observer')['mission_details']['target_ids'],['B'])
    def test_hold_window_then_extract(self):
        c=tiny(start=2);c['mission'].update(type='hold_extract',hold_until=3,hold_node=4)
        self.reset(c);self.step(2);self.assertEqual(self.obs()['own_mission']['kind'],'hold')
        self.assertEqual(self.obs()['own_mission']['completed'],0)
        s=self.step();self.assertEqual(s['winner_reason'],'mission_completed')
        self.assertEqual(self.obs()['own_mission']['kind'],'breakthrough')
    def test_hold_breach(self):
        c=tiny();c['mission'].update(type='hold_extract',hold_until=3,hold_node=7)
        self.reset(c);s=self.step();self.assertEqual(s['winner_reason'],'hold_breached')
    def test_invalid_mission_reset_is_atomic(self):
        a=self.reset(tiny());bad=tiny();bad['mission']['target_ids']=['SECRET']
        with self.assertRaises(ValueError):self.reset(bad)
        self.assertEqual(self.obs('observer'),a)
    def test_terminal_exit_is_not_a_ghost_contact(self):
        c=tiny(start=2,required=2);c['units'][2]['node']=4
        self.reset(c);m=BattleMemory(':memory:')
        try:
            m.observe(self.obs('blue'));self.step();m.observe(self.obs('blue'));self.step();obs=self.obs('blue');m.observe(obs)
            self.assertNotIn(1,[g['id'] for g in m.last_contacts(obs)])
            self.assertEqual(next(t for t in m.decision_context(obs)['tracks'] if t['unit_id']==1)['status'],'confirmed_exited')
        finally:m.close()
    def test_all_proposals_accept_both_sides_and_rotated_map(self):
        for kind in ('breakthrough','hidden','hold_extract'):
            for swap in (False,True):
                for rotate in (False,True):
                    cfg=mission_scenario(kind,'B',swap,rotate)
                    for side in ('red','blue'):
                        self.reset(cfg)
                        for p in plans(self.obs(side)):
                            self.reset(cfg);s=self.step(0,p['orders'])
                            self.assertTrue(s['batch_accepted'],(kind,swap,rotate,side,p['id'],s['order_checks']))
    def test_mission_progress_is_not_loss_of_control(self):
        self.reset(tiny(required=2));before=self.obs();self.step(1,[order(1,2)]);after=self.obs()
        self.assertIn('mission_progress',triggers(after,before));self.assertNotIn('unit_lost_control',triggers(after,before))
    def test_hold_phase_triggers_replan(self):
        c=tiny();c['mission'].update(type='hold_extract',hold_until=2,hold_node=4)
        self.reset(c);before=self.obs();self.step(2)
        self.assertIn('mission_phase_changed',triggers(self.obs(),before))


class MissionReasoning(unittest.TestCase):
    def setUp(self):
        self.p=BattleProcess();self.p.request(dict(command='reset',scenario=mission_scenario('hidden','A')))
        self.obs=self.p.request(dict(command='state',side='blue'));self.obs['tick']=20
        self.obs['own_mission']['remaining_ticks']=80
        self.m=BattleMemory(':memory:')
    def tearDown(self):self.m.close();self.p.close()
    def context(self,mode='memory',previous=None):return self.m.decision_context(self.obs,mode,previous)
    def result(self,context=None,change=None,previous=None):
        context=context or self.context()
        data=dict(goal_hypotheses=[dict(objective='unknown',purpose='unknown',confidence='low',support=[],counter_evidence=[],basis='当前不足以区分两个出口',would_change_if='新目击显示主力持续向一侧运动')],
                  selected_plan='guard_balanced',choice_reason='兼顾两个可能出口',information_need='观察两个出口接近路',reconsider_when=['new_contact'])
        if change:change(data)
        return decide_context(self.obs,context,previous,lambda *a,**k:dict(text=json.dumps(data),seconds=0))
    def historical(self,node,tick=1):
        f=copy.deepcopy(self.obs);f['tick']=tick
        f['entities']=[u for u in f['entities'] if u['side']=='blue']+[dict(id=1,side='red',role='light',current_node=node,hp=100,status='READY')]
        self.m.observe(f)
    def test_no_contact_unknown_is_valid(self):self.assertTrue(self.result()['grounding_passed'])
    def test_no_contact_specific_goal_is_rejected(self):
        r=self.result(change=lambda d:d['goal_hypotheses'][0].update(objective='A',purpose='breakthrough'))
        self.assertFalse(r['grounding_passed']);self.assertEqual(r['orders'],[])
    def test_unknown_or_foreign_citation_rejected(self):
        self.historical(11)
        r=self.result(change=lambda d:d['goal_hypotheses'][0].update(objective='A',support=['F1U777']))
        self.assertIn('unknown_or_unrelated_evidence',r['grounding_errors'])
    def test_future_evidence_rejected_before_model(self):
        c=self.context();c['evidence'].append(dict(id='future',tick=99,unit_id=1,text='敌军',kind='sighting'))
        with self.assertRaisesRegex(ValueError,'future_evidence'):self.result(c)
    def test_scope_mismatch_rejected(self):
        c=self.context();c['query']['side']='red'
        with self.assertRaisesRegex(ValueError,'context_scope_mismatch'):self.result(c)
    def test_current_mode_does_not_inherit_old_beliefs_or_sources(self):
        self.historical(11);previous=dict(source_tick=1,goal_hypotheses=[dict(objective='A',purpose='breakthrough')])
        c=self.context('current',previous)
        self.assertFalse(c['evidence']);self.assertFalse(c['prior_beliefs']);self.assertFalse(c['tracks'])
    def test_hypothesis_persists_but_is_not_a_fact(self):
        self.historical(11);previous=dict(source_tick=1,goal_hypotheses=[dict(objective='A',purpose='breakthrough')])
        c=self.context(previous=previous)
        self.assertEqual(c['prior_beliefs'],previous['goal_hypotheses'])
        self.assertTrue(all(e['kind']!='hypothesis' for e in c['evidence']))
    def test_future_and_other_side_memory_excluded(self):
        self.historical(11);self.historical(24,99)
        f=copy.deepcopy(self.obs);f.update(perspective='red',tick=2);f['entities']=[dict(id=777,side='blue',role='light',current_node=4,hp=100,status='READY')];self.m.observe(f)
        c=self.context();self.assertNotIn('777',json.dumps(c));self.assertTrue(all(e['tick']<=20 for e in c['evidence']))
    def test_history_changes_features_not_candidate_plans(self):
        self.historical(9,1);self.historical(10,2);a=self.result()
        self.m.close();self.m=BattleMemory(':memory:');self.historical(21,1);self.historical(22,2);b=self.result()
        self.assertNotEqual(a['derived_features'],b['derived_features']);self.assertEqual(a['proposal_digest'],b['proposal_digest'])
    def test_private_A_B_generate_identical_model_inputs(self):
        a=self.result();self.p.request(dict(command='reset',scenario=mission_scenario('hidden','B')))
        self.obs=self.p.request(dict(command='state',side='blue'));self.obs['tick']=20;self.obs['own_mission']['remaining_ticks']=80
        self.assertEqual(a['input_digest'],self.result()['input_digest'])
    def test_same_current_different_task_changes_actions(self):
        a=scripted_decision(self.obs)['orders'];self.obs['own_mission'].update(kind='breakthrough',targets=[dict(id='A',node=1)],eligible_units=[101,102])
        self.assertNotEqual(a,scripted_decision(self.obs)['orders'])
    def test_explicit_refutation_is_required(self):
        r=self.result(change=lambda d:d['goal_hypotheses'][0].update(would_change_if=''))
        self.assertIn('missing_hypothesis_reason_or_refutation',r['grounding_errors'])
    def test_temporal_features_cite_real_sightings(self):
        self.historical(9,1);self.historical(10,2);c=self.context();ids={e['id'] for e in c['evidence']}
        self.assertTrue(c['derived_features']);self.assertTrue(all(set(f['sources'])<=ids for f in c['derived_features']))
    def test_empty_evidence_schema_forbids_placeholder_citations(self):
        def capture(messages,**kwargs):
            props=kwargs['schema']['properties']['goal_hypotheses']['items']['properties']
            self.assertEqual(props['support']['maxItems'],0)
            self.assertEqual(props['counter_evidence']['maxItems'],0)
            return dict(text=json.dumps(dict(goal_hypotheses=[dict(objective='unknown',purpose='unknown',confidence='low',support=[],counter_evidence=[],basis='无目击',would_change_if='出现新目击')],selected_plan='guard_balanced',choice_reason='分区观察',information_need='接近路',reconsider_when=['new_contact'])))
        self.assertTrue(decide_context(self.obs,self.context(),infer=capture)['grounding_passed'])
    def test_hidden_goal_with_evidence_requires_distinct_alternatives(self):
        self.historical(11)
        self.assertIn('missing_competing_hypothesis',self.result()['grounding_errors'])
    def test_exit_and_simultaneous_rout_have_separate_triggers(self):
        before=copy.deepcopy(self.obs);after=copy.deepcopy(before)
        own=[u for u in after['entities'] if u['side']=='blue']
        own[0]['status']='EXITED';own[1]['status']='ROUTED'
        signals=triggers(after,before)
        self.assertIn('mission_progress',signals);self.assertIn('unit_lost_control',signals)
    def test_new_observation_can_refute_previous_direction(self):
        self.historical(11,1);self.historical(5,2)
        previous=dict(source_tick=1,orders=[],goal_hypotheses=[dict(objective='A',purpose='breakthrough')])
        r=self.result(self.context(previous=previous),previous=previous)
        update=r['feedback']['hypothesis_updates'][0]
        self.assertIn('远离',update['assessment']);self.assertTrue(update['sources'])
    def test_other_side_previous_belief_does_not_enter_context(self):
        previous=dict(side='red',source_tick=1,goal_hypotheses=[dict(objective='A',purpose='breakthrough')])
        self.assertEqual(self.context(previous=previous)['prior_beliefs'],[])


if __name__=='__main__':unittest.main(verbosity=2)
