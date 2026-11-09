import datetime as _dt
import json
import unittest

from tests import _bootstrap as t

BOND = t.BOND
STAKE = BOND // 2


class ChallengeBase(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()
        self.claim_id = t.verified_claim(self.c)
        # fee-free pool so keeper amounts are predictable in split tests
        self.c.pool = t.u256(0)
        self.c.balance = self.c.balance - t.u256(0)

    def claim(self):
        return t.get(self.c, self.claim_id)


class TestChallengeRules(ChallengeBase):
    def test_challenge_locks_stake_and_marks_claim_challenged(self):
        out = json.loads(t.challenge(self.c, self.claim_id))
        self.assertEqual(out["status"], "challenged")
        claim = self.claim()
        self.assertEqual(claim["challenge"]["challenger"], t.CHALLENGER)
        self.assertEqual(claim["challenge"]["stake"], str(STAKE))
        self.assertEqual(claim["challenge_count"], 1)
        self.assertEqual(int(self.c.locked_total), BOND + STAKE)

    def test_minimum_stake_is_half_the_bond_rounded_up(self):
        with self.assertRaises(t.PaymentRejected) as ctx:
            t.challenge(self.c, self.claim_id, stake=STAKE - 1)
        self.assertIn(str(STAKE), str(ctx.exception))
        t.do_withdraw(self.c, t.CHALLENGER)

    def test_owner_cannot_challenge_own_claim(self):
        with self.assertRaises(t.PaymentRejected):
            t.challenge(self.c, self.claim_id, challenger=t.OWNER)

    def test_only_verified_claims_can_be_challenged(self):
        pending_id = t.post(self.c, ref="8")
        with self.assertRaises(t.PaymentRejected):
            t.challenge(self.c, pending_id)
        t.do_withdraw(self.c, t.CHALLENGER)
        t.challenge(self.c, self.claim_id)
        with self.assertRaises(t.PaymentRejected):
            t.challenge(self.c, self.claim_id, challenger=t.STRANGER)

    def test_allegation_length(self):
        with self.assertRaises(t.PaymentRejected):
            t.challenge(self.c, self.claim_id, allegation="too short")
        with self.assertRaises(t.PaymentRejected):
            t.challenge(self.c, self.claim_id, allegation="x" * 501)

    def test_counter_url_is_restricted_to_github_api_evidence(self):
        good = "https://api.github.com/repos/other/project/commits/" + "b" * 40
        t.challenge(self.c, self.claim_id, counter=good)
        self.assertEqual(self.claim()["challenge"]["counter_url"], good)

    def test_bad_counter_urls_are_rejected(self):
        bad = [
            "http://api.github.com/repos/o/r/commits/abc",
            "https://api.github.com.evil.example/repos/o/r/commits/abc",
            "https://user:pw@api.github.com/repos/o/r/commits/abc",
            "https://api.github.com:444/repos/o/r/commits/abc",
            "https://api.github.com/repos/o/r/commits/abc?x=1",
            "https://api.github.com/repos/o/r/commits/abc#frag",
            "https://api.github.com/user",
            "https://api.github.com/search/code?q=secret",
            "https://github.com/o/r/commit/abc",
        ]
        for url in bad:
            with self.assertRaises(t.PaymentRejected, msg=url):
                t.challenge(self.c, self.claim_id, counter=url)
            t.do_withdraw(self.c, t.CHALLENGER)
        self.assertEqual(self.claim()["status"], "verified")
        t.assert_accounting(self, self.c)

    def test_max_challenges(self):
        t.SkillBond.MAX_CHALLENGES = 1
        try:
            t.challenge(self.c, self.claim_id)
            t.resolve(self.c, self.claim_id, t.MODEL_SUPPORTED)
            with self.assertRaises(t.PaymentRejected) as ctx:
                t.challenge(self.c, self.claim_id)
            self.assertIn("maximum", str(ctx.exception))
        finally:
            t.SkillBond.MAX_CHALLENGES = 3


class TestUpheld(ChallengeBase):
    def test_upheld_split_is_exact(self):
        t.challenge(self.c, self.claim_id)
        out = json.loads(t.resolve(self.c, self.claim_id, t.MODEL_UNSUPPORTED))
        claim = self.claim()
        slash = BOND * 8000 // 10000
        to_challenger = slash * 7500 // 10000
        self.assertEqual(out["status"], "overturned")
        self.assertEqual(claim["slashed"], str(slash))
        self.assertEqual(t.pending(self.c, t.CHALLENGER), STAKE + to_challenger)
        self.assertEqual(t.pending(self.c, t.OWNER), BOND - slash)
        # remainder of the slash minus the 50 keeper reward sits in the pool
        self.assertEqual(int(self.c.pool), slash - to_challenger - 50)
        self.assertEqual(t.pending(self.c, t.KEEPER), 50)
        self.assertEqual(int(self.c.locked_total), 0)
        t.assert_accounting(self, self.c)

    def test_upheld_removes_points_adds_a_strike_and_frees_evidence(self):
        before = self.c.get_score(t.OWNER)
        self.assertEqual(before, 25)
        t.challenge(self.c, self.claim_id)
        t.resolve(self.c, self.claim_id, t.MODEL_UNSUPPORTED)
        profile = json.loads(self.c.get_profile(t.OWNER))
        self.assertEqual(profile["strikes"], 1)
        self.assertEqual(profile["penalties"], 25)
        self.assertEqual(profile["score"], 0)
        self.assertFalse(profile["verified"])
        again = t.post(self.c)
        self.assertEqual(again, "claim_1")

    def test_code_facts_changing_after_verification_never_slash(self):
        t.challenge(self.c, self.claim_id)
        pages = t.pr_pages(login="someone-else")
        t.expect_user_error(self, t.resolve, self.c, self.claim_id, None, pages=pages)
        self.assertEqual(self.claim()["status"], "challenged")

    def test_prompt_contains_allegation_and_counter_evidence(self):
        counter = "https://api.github.com/repos/other/project/commits/" + "b" * 40
        t.challenge(self.c, self.claim_id, allegation="This code was copied from other/project", counter=counter)
        pages = t.pr_pages()
        pages[counter] = {"sha": "b" * 40, "commit": {"message": "original sort implementation"}}
        prompts = []
        t.resolve(self.c, self.claim_id, t.MODEL_SUPPORTED, pages=pages, prompts=prompts)
        self.assertIn("=== CHALLENGER ALLEGATION ===", prompts[0])
        self.assertIn("copied from other/project", prompts[0])
        self.assertIn("original sort implementation", prompts[0])

    def test_keeper_who_is_a_party_gets_no_reward(self):
        t.challenge(self.c, self.claim_id)
        t.resolve(self.c, self.claim_id, t.MODEL_UNSUPPORTED, caller=t.CHALLENGER)
        slash = BOND * 8000 // 10000
        self.assertEqual(t.pending(self.c, t.CHALLENGER), STAKE + slash * 7500 // 10000)
        t.assert_accounting(self, self.c)


class TestDismissed(ChallengeBase):
    def test_dismissed_split_is_exact(self):
        t.challenge(self.c, self.claim_id)
        out = json.loads(t.resolve(self.c, self.claim_id, t.MODEL_SUPPORTED))
        to_claimant = STAKE * 6000 // 10000
        self.assertEqual(out["status"], "verified")
        self.assertEqual(t.pending(self.c, t.OWNER), to_claimant)
        self.assertEqual(t.pending(self.c, t.CHALLENGER), 0)
        self.assertEqual(int(self.c.pool), STAKE - to_claimant - 50)
        self.assertEqual(int(self.c.locked_total), BOND)
        t.assert_accounting(self, self.c)

    def test_dismissed_claim_survives_with_bonus_and_log(self):
        t.challenge(self.c, self.claim_id)
        t.resolve(self.c, self.claim_id, t.MODEL_SUPPORTED)
        claim = self.claim()
        self.assertEqual(claim["status"], "verified")
        self.assertEqual(claim["survived"], 1)
        self.assertEqual(claim["challenge_log"][0]["outcome"], "dismissed")
        self.assertEqual(self.c.get_score(t.OWNER), 25 + t.SkillBond.SURVIVAL_BONUS)

    def test_claim_can_be_challenged_again_after_dismissal(self):
        t.challenge(self.c, self.claim_id)
        t.resolve(self.c, self.claim_id, t.MODEL_SUPPORTED)
        t.challenge(self.c, self.claim_id, challenger=t.STRANGER)
        self.assertEqual(self.claim()["challenge_count"], 2)


class TestUndeterminedAndVoid(ChallengeBase):
    def test_undetermined_reverts_and_keeps_challenge_open(self):
        t.challenge(self.c, self.claim_id)
        t.expect_user_error(self, t.resolve, self.c, self.claim_id, t.MODEL_UNDETERMINED)
        t.expect_user_error(self, t.resolve, self.c, self.claim_id, {})
        self.assertEqual(self.claim()["status"], "challenged")

    def test_void_only_after_deadline_and_refunds_the_stake(self):
        t.challenge(self.c, self.claim_id)
        t.set_caller(t.STRANGER)
        t.expect_user_error(self, self.c.void_challenge, self.claim_id)
        t.CLOCK.advance(t.SkillBond.RESOLUTION_TIMEOUT_SECONDS + 1)
        self.c.void_challenge(self.claim_id)
        claim = self.claim()
        self.assertEqual(claim["status"], "verified")
        self.assertEqual(claim["challenge_count"], 1)
        self.assertEqual(t.pending(self.c, t.CHALLENGER), STAKE)
        self.assertEqual(int(self.c.locked_total), BOND)
        t.assert_accounting(self, self.c)

    def test_void_without_challenge(self):
        t.set_caller(t.STRANGER)
        t.expect_user_error(self, self.c.void_challenge, self.claim_id)

    def test_resolve_without_challenge(self):
        t.expect_user_error(self, t.resolve, self.c, self.claim_id, t.MODEL_SUPPORTED)


class TestReleaseBond(ChallengeBase):
    def test_release_after_window_finalizes_and_returns_bond(self):
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        out = json.loads(self.c.release_bond(self.claim_id))
        self.assertEqual(out["status"], "finalized")
        self.assertEqual(t.pending(self.c, t.OWNER), BOND)
        self.assertEqual(self.c.get_score(t.OWNER), 25)
        t.assert_accounting(self, self.c)

    def test_release_before_window_is_refused(self):
        t.set_caller(t.OWNER)
        t.expect_user_error(self, self.c.release_bond, self.claim_id)

    def test_only_owner_can_release(self):
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.STRANGER)
        t.expect_user_error(self, self.c.release_bond, self.claim_id)

    def test_cannot_release_while_challenged(self):
        t.challenge(self.c, self.claim_id)
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        t.expect_user_error(self, self.c.release_bond, self.claim_id)

    def test_finalized_claim_cannot_be_challenged_or_released_twice(self):
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        self.c.release_bond(self.claim_id)
        with self.assertRaises(t.PaymentRejected):
            t.challenge(self.c, self.claim_id)
        t.expect_user_error(self, self.c.release_bond, self.claim_id)

    def test_release_keeps_evidence_blocked(self):
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        self.c.release_bond(self.claim_id)
        with self.assertRaises(t.PaymentRejected):
            t.call_payable(self.c, "post_claim", BOND, "pull_request", t.REPO, "7", t.STATEMENT, t.TAGS)


if __name__ == "__main__":
    unittest.main()
