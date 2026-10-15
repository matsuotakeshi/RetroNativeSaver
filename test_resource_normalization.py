"""Independent invalid-resource settings now follow normal-cycle policy."""
import copy
from pathlib import Path
import random
import unittest

import resource_policy as policy
from independent_slots import select_slot
from tests_fixtures import legacy_v064 as normal


class ResourceNormalizationTests(unittest.TestCase):
    def test_usage_matches_normal_for_missing_and_malformed_groups_and_weights(self):
        groups=['', ' ', 'heavy_cd', ' heavy_cd ',None,0,False,[],{'x':1}]
        weights=[0,1,2,-1,'2','bad',None,2.8,[],{},float('inf')]
        for group in groups:
            for weight in weights:
                picks=[(dict(id='a',resource_group=group,resource_weight=weight),Path('a')),
                       (dict(id='b',resource_group='heavy_cd',resource_weight=1),Path('b'))]
                counts,usage=policy.independent_usage(picks)
                self.assertEqual(counts,{'a':1,'b':1})
                self.assertEqual(usage,normal._resource_group_usage_from_picks(picks))
        self.assertEqual(policy.independent_usage([(dict(id='a'),None)]),({'a':1},{}))

    def test_candidate_and_favorite_reservation_match_normal_matrix(self):
        groups=['',' ', 'heavy_cd',' heavy_cd ',None,0,False,[],{'x':1}]
        weights=[0,1,2,-1,'2','bad',None,[],float('nan')]
        configs=[{}, {'resource_groups':None},{'resource_groups':[]},{'resource_groups':'bad'},
                 {'resource_groups':{'heavy_cd':None}},{'resource_groups':{'heavy_cd':[]}}]
        configs += [{'resource_groups':{'heavy_cd':{'max_weight':x}}}
                    for x in [0,1,2,-1,'2','bad',None,[],float('inf')]]
        for group in groups:
            for weight in weights:
                system=dict(id='a',resource_group=group,resource_weight=weight,max_concurrent=3)
                picks=[(dict(id='b',resource_group=' heavy_cd ',resource_weight='bad'),None)]
                before=copy.deepcopy(picks)
                counts,usage=policy.independent_usage(picks)
                for cfg in configs:
                    expected=normal._resource_group_can_add(system,normal._resource_group_usage_from_picks(picks),cfg)
                    self.assertEqual(policy.independent_can_add(system,counts,usage,cfg),expected)
                    self.assertEqual(policy.independent_fits(system,picks,cfg),expected)
                self.assertEqual(picks,before)

    def test_concrete_defaults_and_limits(self):
        invalid=dict(id='a',resource_group=' heavy_cd ',resource_weight='bad')
        cfg={'resource_groups':{'heavy_cd':{'max_weight':1}}}
        self.assertEqual(policy.independent_usage([(invalid,None)])[1],{'heavy_cd':1})
        self.assertTrue(policy.independent_fits(invalid,[],cfg))
        self.assertFalse(policy.independent_fits(invalid,[(invalid,None)],cfg))
        for limit in (None,'bad',[],0,-1):
            self.assertTrue(policy.independent_fits(invalid,[(invalid,None)],
                {'resource_groups':{'heavy_cd':{'max_weight':limit}}}))
        negative=dict(invalid,resource_weight=-1)
        self.assertTrue(policy.independent_fits(negative,[(invalid,None)],cfg))

    def test_group_string_conversion_is_the_normal_policy_even_for_null(self):
        system=dict(id='a',resource_group=None,resource_weight=2)
        self.assertEqual(policy.independent_usage([(system,None)])[1],{'None':2})
        self.assertFalse(policy.independent_fits(system,[],{'resource_groups':{'None':{'max_weight':1}}}))

    def test_concurrency_invalid_values_still_raise_and_caps_still_apply(self):
        for value in ('bad',None,[],{}):
            system=dict(id='a',max_concurrent=value)
            for operation,args in ((policy.independent_can_add,({}, {}, {})),(policy.independent_fits,([],{}))):
                with self.assertRaises((ValueError,TypeError)):operation(system,*args)
        for value in (0,-1):
            system=dict(id='a',max_concurrent=value,resource_weight='bad')
            self.assertFalse(policy.independent_can_add(system,{}, {},{}))
            self.assertFalse(policy.independent_fits(system,[],{}))

    def test_favorite_reservation_and_occupied_invalid_weight_share_budget(self):
        favorite=dict(id='f',resource_group=' heavy_cd ',resource_weight='bad')
        heavy=dict(id='h',resource_group='heavy_cd',resource_weight=1)
        light=dict(id='l')
        systems=[favorite,heavy,light];catalogs={s['id']:[Path(s['id'])] for s in systems}
        fav=[(favorite,Path('f'))];cfg={'resource_groups':{'heavy_cd':{'max_weight':1}}}
        for seed in range(30):
            # Slot 1 reserves favorite capacity even before it starts.
            pick=select_slot(1,systems,catalogs,cfg,[],fav,set(),set(),random.Random(seed),normal_occupied=[])
            self.assertEqual(pick[0]['id'],'l')
            pick=select_slot(0,systems,catalogs,cfg,[],fav,set(),set(),random.Random(seed))
            self.assertEqual(pick,fav[0])
            pick=select_slot(1,systems,catalogs,cfg,fav,fav,set(),set(),random.Random(seed),normal_occupied=[])
            self.assertEqual(pick[0]['id'],'l')

    def test_malformed_group_container_no_longer_stops_selection(self):
        system=dict(id='a',resource_group='heavy_cd',resource_weight='bad')
        rom=Path('a');favorites=[(system,rom)]
        for groups in (None,[],False,'bad',{'heavy_cd':None},{'heavy_cd':{'max_weight':'bad'}}):
            pick=select_slot(0,[system],{'a':[rom]},{'resource_groups':groups},[],favorites,set(),set(),random.Random(1))
            self.assertEqual(pick,favorites[0])


if __name__=='__main__':unittest.main()
