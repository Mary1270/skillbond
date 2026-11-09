import json
import unittest

from tests import _bootstrap as t


class TestPostClaim(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()
        t.bind(self.c)

    def test_post_locks_the_bond_and_anchors_evidence(self):
        claim_id = t.post(self.c)
        claim = t.get(self.c, claim_id)
        self.assertEqual(claim_id, "claim_0")
        self.assertEqual(claim["status"], "pending")
        self.assertEqual(claim["bond"], str(t.BOND))
        self.assertEqual(claim["evidence_url"], t.pr_url(7))
        self.assertEqual(claim["tags"], ["python", "sorting"])
        self.assertEqual(claim["login"], "octodev")
        self.assertEqual(int(self.c.locked_total), t.BOND)
        t.assert_accounting(self, self.c)

    def test_requires_a_bound_login(self):
        t.set_caller(t.STRANGER)
        with self.assertRaises(t.PaymentRejected) as ctx:
            t.call_payable(self.c, "post_claim", t.BOND, "pull_request", t.REPO, "7", t.STATEMENT, t.TAGS)
        self.assertIn("Bind your GitHub login", str(ctx.exception))
        self.assertEqual(t.pending(self.c, t.STRANGER), t.BOND)
        t.assert_accounting(self, self.c)

    def test_rejected_payable_is_refunded_not_stuck(self):
        t.set_caller(t.OWNER)
        with self.assertRaises(t.PaymentRejected):
            t.call_payable(self.c, "post_claim", t.BOND, "pull_request", "bad repo", "7", t.STATEMENT, t.TAGS)
        self.assertEqual(t.do_withdraw(self.c, t.OWNER), t.BOND)
        t.assert_accounting(self, self.c)

    def test_input_validation(self):
        bad = [
            ("branch", t.REPO, "7", t.STATEMENT, t.TAGS),
            ("commit", t.REPO, "abc123", t.STATEMENT, t.TAGS),
            ("commit", t.REPO, "g" * 40, t.STATEMENT, t.TAGS),
            ("pull_request", t.REPO, "0", t.STATEMENT, t.TAGS),
            ("pull_request", t.REPO, "seven", t.STATEMENT, t.TAGS),
            ("release", t.REPO, "", t.STATEMENT, t.TAGS),
            ("pull_request", "noslash", "7", t.STATEMENT, t.TAGS),
            ("pull_request", t.REPO, "7", "short", t.TAGS),
            ("pull_request", t.REPO, "7", "x" * 281, t.TAGS),
            ("pull_request", t.REPO, "7", t.STATEMENT, ""),
            ("pull_request", t.REPO, "7", t.STATEMENT, "a,b,c,d"),
            ("pull_request", t.REPO, "7", t.STATEMENT, "Bad Tag!"),
        ]
        t.set_caller(t.OWNER)
        for args in bad:
            with self.assertRaises(t.PaymentRejected, msg=str(args)):
                t.call_payable(self.c, "post_claim", t.BOND, *args)
            t.do_withdraw(self.c, t.OWNER)
        self.assertEqual(int(self.c.claim_count), 0)
        t.assert_accounting(self, self.c)

    def test_bond_below_minimum(self):
        t.set_caller(t.OWNER)
        with self.assertRaises(t.PaymentRejected):
            t.call_payable(self.c, "post_claim", t.SkillBond.MIN_BOND - 1, "pull_request", t.REPO, "7", t.STATEMENT, t.TAGS)

    def test_tags_are_normalised_and_deduplicated(self):
        claim_id = t.post(self.c, tags=" Rust ; rust , ZK ")
        self.assertEqual(t.get(self.c, claim_id)["tags"], ["rust", "zk"])

    def test_commit_ref_is_lowercased(self):
        claim_id = t.post(self.c, kind="commit", ref="A" * 40)
        self.assertEqual(t.get(self.c, claim_id)["ref"], "a" * 40)

    def test_release_tag_with_slash_is_url_encoded(self):
        claim_id = t.post(self.c, kind="release", ref="v1/rc.1")
        self.assertTrue(t.get(self.c, claim_id)["evidence_url"].endswith("/releases/tags/v1%2Frc.1"))

    def test_same_evidence_cannot_be_claimed_twice(self):
        t.post(self.c)
        t.set_caller(t.OWNER)
        with self.assertRaises(t.PaymentRejected) as ctx:
            t.call_payable(self.c, "post_claim", t.BOND, "pull_request", t.REPO.upper(), "7", "Another statement about it", "go")
        self.assertIn("already claimed by claim_0", str(ctx.exception))

    def test_evidence_is_freed_after_withdraw(self):
        first = t.post(self.c)
        t.set_caller(t.OWNER)
        self.c.withdraw_claim(first)
        second = t.post(self.c)
        self.assertEqual(second, "claim_1")

    def test_active_claim_cap(self):
        t.SkillBond.MAX_ACTIVE_CLAIMS = 2
        try:
            t.post(self.c, ref="1")
            t.post(self.c, ref="2")
            t.set_caller(t.OWNER)
            with self.assertRaises(t.PaymentRejected):
                t.call_payable(self.c, "post_claim", t.BOND, "pull_request", t.REPO, "3", t.STATEMENT, t.TAGS)
        finally:
            t.SkillBond.MAX_ACTIVE_CLAIMS = 30

    def test_total_claim_cap(self):
        t.SkillBond.MAX_CLAIMS_PER_ADDRESS = 2
        try:
            first = t.post(self.c, ref="1")
            t.post(self.c, ref="2")
            t.set_caller(t.OWNER)
            self.c.withdraw_claim(first)
            with self.assertRaises(t.PaymentRejected):
                t.call_payable(self.c, "post_claim", t.BOND, "pull_request", t.REPO, "3", t.STATEMENT, t.TAGS)
        finally:
            t.SkillBond.MAX_CLAIMS_PER_ADDRESS = 80


class TestWithdrawClaim(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()
        t.bind(self.c)
        self.claim_id = t.post(self.c)

    def test_owner_gets_full_bond_back(self):
        t.set_caller(t.OWNER)
        self.c.withdraw_claim(self.claim_id)
        self.assertEqual(t.get(self.c, self.claim_id)["status"], "withdrawn")
        self.assertEqual(t.pending(self.c, t.OWNER), t.BOND)
        self.assertEqual(t.do_withdraw(self.c, t.OWNER), t.BOND)
        t.assert_accounting(self, self.c)
        self.assertEqual(int(self.c.balance), 0)

    def test_only_owner_and_only_pending(self):
        t.set_caller(t.STRANGER)
        t.expect_user_error(self, self.c.withdraw_claim, self.claim_id)
        t.verify(self.c, self.claim_id)
        t.set_caller(t.OWNER)
        t.expect_user_error(self, self.c.withdraw_claim, self.claim_id)

    def test_unknown_claim(self):
        t.expect_user_error(self, self.c.withdraw_claim, "claim_99")


class TestWithdraw(unittest.TestCase):
    def test_nothing_to_withdraw(self):
        c = t.make_contract()
        t.set_caller(t.STRANGER)
        t.expect_user_error(self, c.withdraw) if False else None
        with self.assertRaises(t.gl.vm.UserError):
            c.withdraw()

    def test_double_withdraw_fails(self):
        c = t.make_contract()
        t.bind(c)
        claim_id = t.post(c)
        t.set_caller(t.OWNER)
        c.withdraw_claim(claim_id)
        t.do_withdraw(c, t.OWNER)
        with self.assertRaises(t.gl.vm.UserError):
            c.withdraw()


if __name__ == "__main__":
    unittest.main()
