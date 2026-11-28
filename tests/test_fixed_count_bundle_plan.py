"""Offline exact-count selection regression tests; no network or billing."""
import itertools
import unittest

from aame.video import Cue, VideoError, _select_exact, plan_bundle, rank_candidates


class BundlePlanTests(unittest.TestCase):
    def test_greedy_counterexample_and_exact_render_selection(self):
        cues = [Cue(i * 10000, (i + 1) * 10000, "one two three four five six seven eight nine ten")
                for i in range(6)]
        self.assertEqual(rank_candidates(cues, minimum_ms=20000)[0].end_ms, 30000)
        plan = plan_bundle(cues)
        self.assertEqual([(c.start_ms, c.end_ms) for c in plan],
                         [(0, 20000), (20000, 40000), (40000, 60000)])
        self.assertEqual(plan, plan_bundle(cues))
        for c in plan:
            self.assertEqual(_select_exact(cues, (c.start_ms, c.end_ms),
                                           20000, 35000, ()), c)
        with self.assertRaises(VideoError):
            _select_exact(cues, (1, 20000), 20000, 35000, ())
        with self.assertRaises(VideoError):
            _select_exact(cues, (0, 20000), 20000, 35000, ((10000, 11000),))

    def test_infeasible_and_invalid_profiles(self):
        cues = [Cue(i * 10000, (i + 1) * 10000, "caption")
                for i in range(5)]
        with self.assertRaises(VideoError):
            plan_bundle(cues)
        for count in (0, True, 11):
            with self.subTest(count=count), self.assertRaises(VideoError):
                plan_bundle(cues, count=count)
        with self.assertRaises(VideoError):
            plan_bundle([Cue(0, 20000, "one"), Cue(10000, 30000, "two")])
        with self.assertRaises(VideoError):
            plan_bundle(cues, count=1, minimum_ms=35001)

    def test_negative_scores_and_exclusions(self):
        cues = [Cue(i * 35000, (i + 1) * 35000, "one") for i in range(4)]
        plan = plan_bundle(cues, excluded_windows=((35000, 70000),))
        self.assertEqual([c.start_ms for c in plan], [0, 70000, 105000])
        self.assertTrue(all(c.score < 0 for c in plan))

    def test_score_matches_small_exhaustive_search(self):
        cues = [Cue(i * 4000, (i + 1) * 4000, "word " * (i + 1))
                for i in range(5)]
        candidates = rank_candidates(cues, limit=20, minimum_ms=4000, maximum_ms=12000)
        valid = [pair for pair in itertools.combinations(candidates, 2)
                 if pair[0].end_ms <= pair[1].start_ms or pair[1].end_ms <= pair[0].start_ms]
        best = max(sum(c.score for c in pair) for pair in valid)
        plan = plan_bundle(cues, count=2, minimum_ms=4000, maximum_ms=12000)
        self.assertEqual(sum(c.score for c in plan), best)

    def test_not_limited_to_top_twenty(self):
        # Twenty-five isolated high-score windows cannot replace the final
        # low-score candidate when the other high-score windows are excluded.
        # More than twenty windows also exercise the suffix DP without a heap cap.
        cues = [Cue(i * 23000, i * 23000 + 20000, "one two three")
                for i in range(26)]
        excluded = [(c.start_ms, c.end_ms) for c in cues[:23]]
        plan = plan_bundle(cues, excluded_windows=excluded)
        self.assertEqual([c.start_ms for c in plan], [c.start_ms for c in cues[-3:]])
