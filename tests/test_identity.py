import json
import unittest

from tests._bootstrap import *  # noqa: F401,F403
from tests import _bootstrap as t


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()

    def test_bind_with_valid_gist(self):
        out = json.loads(t.bind(self.c))
        self.assertEqual(out, {"address": t.OWNER, "login": "octodev"})
        self.assertEqual(self.c.get_login(t.OWNER), "octodev")
        self.assertEqual(self.c.get_address_for_login("OCTODEV"), t.OWNER)

    def test_gist_owned_by_someone_else_is_rejected(self):
        t.set_caller(t.OWNER)
        pages = {t.gist_url("abc12345"): t.gist_json("someone-else", t.OWNER)}
        msg = t.expect_user_error(self, t.run_with, lambda: self.c.bind_github("OctoDev", "abc12345"), pages)
        self.assertIn("not owned", msg)
        self.assertEqual(self.c.get_login(t.OWNER), "")

    def test_gist_without_the_wallet_line_is_rejected(self):
        t.set_caller(t.OWNER)
        pages = {t.gist_url("abc12345"): t.gist_json("OctoDev", t.STRANGER)}
        msg = t.expect_user_error(self, t.run_with, lambda: self.c.bind_github("OctoDev", "abc12345"), pages)
        self.assertIn("skillbond:", msg)

    def test_wallet_line_is_case_insensitive(self):
        t.set_caller(t.OWNER)
        pages = {t.gist_url("abc12345"): t.gist_json("OctoDev", content="Proof: SKILLBOND:" + t.OWNER.upper().replace("0X", "0x"))}
        t.run_with(lambda: self.c.bind_github("OctoDev", "abc12345"), pages)
        self.assertEqual(self.c.get_login(t.OWNER), "octodev")

    def test_unreadable_gist_is_rejected(self):
        t.set_caller(t.OWNER)
        msg = t.expect_user_error(self, t.run_with, lambda: self.c.bind_github("OctoDev", "abc12345"), {})
        self.assertIn("could not be read", msg)

    def test_login_cannot_be_bound_twice(self):
        t.bind(self.c)
        t.set_caller(t.SECOND_OWNER)
        pages = {t.gist_url("def45678"): t.gist_json("OctoDev", t.SECOND_OWNER)}
        msg = t.expect_user_error(self, t.run_with, lambda: self.c.bind_github("octodev", "def45678"), pages)
        self.assertIn("already bound to another wallet", msg)

    def test_wallet_cannot_bind_twice(self):
        t.bind(self.c)
        msg = t.expect_user_error(self, self.c.bind_github, "Other", "def45678")
        self.assertIn("already bound", msg)

    def test_a_gist_cannot_be_reused(self):
        t.bind(self.c)
        t.set_caller(t.OWNER)
        self.c.unbind_github()
        pages = {t.gist_url("abc12345abc12345"): t.gist_json("OctoDev", t.OWNER)}
        msg = t.expect_user_error(self, t.run_with, lambda: self.c.bind_github("OctoDev", "abc12345abc12345"), pages)
        self.assertIn("already used", msg)

    def test_bad_inputs(self):
        t.set_caller(t.OWNER)
        t.expect_user_error(self, self.c.bind_github, "not a login!", "abc12345")
        t.expect_user_error(self, self.c.bind_github, "OctoDev", "not-hex!")

    def test_unbind_blocked_by_active_claim_then_allowed(self):
        t.bind(self.c)
        claim_id = t.post(self.c)
        t.set_caller(t.OWNER)
        t.expect_user_error(self, self.c.unbind_github)
        self.c.withdraw_claim(claim_id)
        self.c.unbind_github()
        self.assertEqual(self.c.get_login(t.OWNER), "")
        self.assertEqual(self.c.get_address_for_login("octodev"), "")

    def test_unbind_when_not_bound(self):
        t.set_caller(t.STRANGER)
        t.expect_user_error(self, self.c.unbind_github)

    def test_login_can_be_rebound_by_a_new_wallet_after_unbind(self):
        t.bind(self.c)
        t.set_caller(t.OWNER)
        self.c.unbind_github()
        t.bind(self.c, owner=t.SECOND_OWNER, gist="fff99999")
        self.assertEqual(self.c.get_address_for_login("octodev"), t.SECOND_OWNER)


if __name__ == "__main__":
    unittest.main()
