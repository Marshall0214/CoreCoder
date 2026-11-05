"""Public examples derived from join's Issue contract; not independent grading tests."""
import unittest

from toolz import join


class Reproduce(unittest.TestCase):
    def test_unmatched_duplicate_keys_emitted_once_per_row(self):
        left=[(10,'matched'),(20,'orphan-a'),(20,'orphan-b')]
        right=[(10,'right')]
        self.assertCountEqual(list(join(0,left,0,right,right_default=None)),
            [((10,'matched'),(10,'right')),((20,'orphan-a'),None),((20,'orphan-b'),None)])

    def test_empty_right_retains_each_left_once(self):
        left=[{'id':5,'value':'a'},{'id':8,'value':'b'}]
        self.assertCountEqual(list(join('id',left,'id',[],right_default='absent')),
                              [(left[0],'absent'),(left[1],'absent')])


class Preserve(unittest.TestCase):
    def test_inner_join_many_to_many(self):
        left=[(3,'l1'),(3,'l2')]
        right=[(3,'r1'),(3,'r2')]
        self.assertCountEqual(list(join(0,left,0,right)),[(l,r) for l in left for r in right])

    def test_right_join_unmatched(self):
        self.assertCountEqual(list(join(0,[(4,'l')],0,[(4,'r'),(9,'orphan')],left_default=None)),
                              [((4,'l'),(4,'r')),(None,(9,'orphan'))])

    def test_inner_join_empty_left(self):
        self.assertEqual(list(join(lambda x:x,[],lambda x:x,[1,2])),[])
