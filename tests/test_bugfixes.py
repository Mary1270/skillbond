import json
import unittest
from unittest.mock import patch

from tests import _bootstrap as t


class TestRenameDoesNotSlash(unittest.TestCase):
    """A repository rename or a GitHub login change after verification must
    not let a challenger slash a claim that was true when it was verified."""

    def setUp(self):
        self.c = t.make_contract()
        self.claim_id = t.verified_claim(self.c)
        t.challenge(self.c, self.claim_id)

    def test_login_renamed_on_github_is_undetermined_not_overturned(self):
        pages = t.pr_pages(login="octodev-renamed")
        t.expect_user_error(self, t.resolve, self.c, self.claim_id, t.MODEL_UNSUPPORTED, pages=pages)
        self.assertEqual(t.get(self.c, self.claim_id)["status"], "challenged")

    def test_repository_renamed_is_undetermined_not_overturned(self):
        pages = {t.pr_url(7): t.pr_json(7, repo="acme/widgets-v2")}
        t.expect_user_error(self, t.resolve, self.c, self.claim_id, t.MODEL_UNSUPPORTED, pages=pages)
        self.assertEqual(t.get(self.c, self.claim_id)["status"], "challenged")

    def test_model_can_still_uphold_when_facts_hold(self):
        out = json.loads(t.resolve(self.c, self.claim_id, t.MODEL_UNSUPPORTED))
        self.assertEqual(out["status"], "overturned")


class TestKeeperRewardCannotDrainPool(unittest.TestCase):
    """A verifier that is a sybil of the claimant must not be able to pull
    keeper rewards out of a pool funded by other people's slashes."""

    def test_supported_verification_pays_no_keeper_reward(self):
        c = t.make_contract()
        c.pool = t.u256(10000)
        c.balance = c.balance + t.u256(10000)
        claim_id = t.post(c) if t.bind(c) else None
        t.verify(c, claim_id, caller=t.STRANGER)
        self.assertEqual(t.pending(c, t.STRANGER), 0)
        self.assertEqual(int(c.pool), 10000)
        t.assert_accounting(self, c)

    def test_reward_is_capped_by_what_the_call_added_to_the_pool(self):
        t.SkillBond.KEEPER_REWARD = 10 ** 9
        try:
            c = t.make_contract()
            c.pool = t.u256(50000)
            c.balance = c.balance + t.u256(50000)
            t.bind(c)
            claim_id = t.post(c)
            t.verify(c, claim_id, pages=t.pr_pages(login="x"), model=None, caller=t.STRANGER)
            fee = t.BOND * 1000 // 10000
            self.assertEqual(t.pending(c, t.STRANGER), fee)
            self.assertEqual(int(c.pool), 50000)
            t.assert_accounting(self, c)
        finally:
            t.SkillBond.KEEPER_REWARD = 50


class TestVoidCannotLockBondForever(unittest.TestCase):
    """Voided challenges must count, so a challenger cannot keep a bond
    locked forever by re-filing a challenge after every void."""

    def test_voids_count_toward_the_challenge_limit(self):
        c = t.make_contract()
        claim_id = t.verified_claim(c)
        for _ in range(t.SkillBond.MAX_CHALLENGES):
            t.challenge(c, claim_id)
            t.CLOCK.advance(t.SkillBond.RESOLUTION_TIMEOUT_SECONDS + 1)
            t.set_caller(t.STRANGER)
            c.void_challenge(claim_id)
        with self.assertRaises(t.PaymentRejected):
            t.challenge(c, claim_id)
        t.set_caller(t.OWNER)
        c.release_bond(claim_id)
        self.assertEqual(t.get(c, claim_id)["status"], "finalized")


class TestScoreFollowsBinding(unittest.TestCase):
    """Other contracts read get_score directly. A wallet that is no longer
    bound to the GitHub login that earned the points must not keep them."""

    def setUp(self):
        self.c = t.make_contract()
        self.claim_id = t.verified_claim(self.c)
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        self.c.release_bond(self.claim_id)

    def test_unbound_wallet_scores_zero(self):
        t.set_caller(t.OWNER)
        self.c.unbind_github()
        self.assertEqual(self.c.get_score(t.OWNER), 0)
        self.assertEqual(self.c.get_skill_score(t.OWNER, "python"), 0)
        self.assertEqual(self.c.get_badge(t.OWNER), "NONE")

    def test_rebinding_the_same_login_restores_the_score(self):
        t.set_caller(t.OWNER)
        self.c.unbind_github()
        t.bind(self.c, gist="abcd9999")
        self.assertEqual(self.c.get_score(t.OWNER), 25)

    def test_strikes_still_count_after_rebinding_another_login(self):
        c = t.make_contract()
        claim_id = t.verified_claim(c)
        t.challenge(c, claim_id)
        t.resolve(c, claim_id, t.MODEL_UNSUPPORTED)
        t.set_caller(t.OWNER)
        c.unbind_github()
        t.bind(c, login="Fresh", gist="abcd7777")
        self.assertEqual(json.loads(c.get_profile(t.OWNER))["strikes"], 1)

    def test_bound_wallet_counter_drops_on_unbind(self):
        t.set_caller(t.OWNER)
        self.c.unbind_github()
        self.assertEqual(json.loads(self.c.get_stats())["bound_wallets"], 0)


class TestNondetClosuresNeverRaise(unittest.TestCase):
    """An exception inside a non-deterministic closure crashes the whole
    transaction on GenVM; malformed GitHub JSON must become a retry."""

    def setUp(self):
        self.c = t.make_contract()
        t.bind(self.c)

    def test_pull_request_with_non_object_base(self):
        claim_id = t.post(self.c)
        t.verify(self.c, claim_id, pages={t.pr_url(7): t.pr_json(base="main")}, model=None)
        self.assertEqual(t.get(self.c, claim_id)["status"], "rejected")

    def test_unexpected_exception_inside_compute_is_contained(self):
        ctx = {"mode": "verify", "kind": "pull_request", "repo": t.REPO, "ref": "7", "login": "octodev", "statement": "x" * 20}
        with patch.object(t.m, "_gather", side_effect=TypeError("boom")):
            out = t.m._verify_compute(ctx)
        self.assertEqual(out["verdict"], "UNDETERMINED")
        with patch.object(t.m, "_load_json_lenient", side_effect=TypeError("boom")):
            out = t.m._gist_compute({"gist_id": "abcd1234", "login": "a", "address": t.OWNER})
        self.assertFalse(out["ok"])
        self.assertTrue(out["retry"])

    def test_commit_with_odd_shapes(self):
        claim_id = t.post(self.c, kind="commit", ref=t.SHA)
        pages = t.commit_pages(commit="not an object", stats=[1], files="nope")
        t.verify(self.c, claim_id, pages=pages)
        self.assertEqual(t.get(self.c, claim_id)["status"], "verified")


if __name__ == "__main__":
    unittest.main()
