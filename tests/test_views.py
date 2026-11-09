import json
import unittest

from tests import _bootstrap as t


class TestComposableViews(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()
        t.bind(self.c)

    def test_empty_address_defaults(self):
        self.assertEqual(self.c.get_score(t.STRANGER), 0)
        self.assertFalse(self.c.is_verified(t.STRANGER))
        self.assertEqual(self.c.get_badge(t.STRANGER), "NONE")
        self.assertEqual(json.loads(self.c.get_claims(t.STRANGER)), [])
        self.assertEqual(self.c.get_skill_score(t.STRANGER, "python"), 0)
        self.assertFalse(self.c.has_skill(t.STRANGER, "python", 1))

    def test_pending_claims_do_not_score(self):
        t.post(self.c)
        self.assertEqual(self.c.get_score(t.OWNER), 0)
        self.assertFalse(self.c.is_verified(t.OWNER))

    def test_score_skill_and_badge_after_verification(self):
        claim_id = t.post(self.c)
        t.verify(self.c, claim_id)
        self.assertEqual(self.c.get_score(t.OWNER), 25)
        self.assertEqual(self.c.get_badge(t.OWNER), "BRONZE")
        self.assertTrue(self.c.is_verified(t.OWNER))
        self.assertTrue(self.c.is_verified_at_least(t.OWNER, 25))
        self.assertFalse(self.c.is_verified_at_least(t.OWNER, 26))
        self.assertEqual(self.c.get_skill_score(t.OWNER, "Python"), 25)
        self.assertEqual(self.c.get_skill_score(t.OWNER, "sorting"), 25)
        self.assertEqual(self.c.get_skill_score(t.OWNER, "rust"), 0)
        self.assertTrue(self.c.has_skill(t.OWNER, "python", 20))
        self.assertFalse(self.c.has_skill(t.OWNER, "python", 26))
        self.assertTrue(self.c.has_skill(t.OWNER, "python", 0))
        self.assertFalse(self.c.has_skill(t.OWNER, "rust", 0))

    def test_is_verified_needs_a_bound_login(self):
        claim_id = t.post(self.c)
        t.verify(self.c, claim_id)
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        self.c.release_bond(claim_id)
        self.c.unbind_github()
        self.assertEqual(self.c.get_score(t.OWNER), 0)
        self.assertFalse(self.c.is_verified(t.OWNER))
        self.assertFalse(self.c.has_skill(t.OWNER, "python", 1))

    def test_badge_ladder(self):
        for score, name in ((0, "NONE"), (19, "NONE"), (20, "BRONZE"), (59, "BRONZE"), (60, "SILVER"),
                            (149, "SILVER"), (150, "GOLD"), (399, "GOLD"), (400, "PLATINUM")):
            self.assertEqual(t.m._badge_for(score), name, score)
        self.assertEqual(t.m._next_badge(0), {"name": "BRONZE", "at": 20})
        self.assertEqual(t.m._next_badge(60), {"name": "GOLD", "at": 150})
        self.assertIsNone(t.m._next_badge(400))

    def test_get_claims_lists_every_status_newest_first(self):
        first = t.post(self.c, ref="1")
        second = t.post(self.c, ref="2")
        t.verify(self.c, second)
        t.set_caller(t.OWNER)
        self.c.withdraw_claim(first)
        rows = json.loads(self.c.get_claims(t.OWNER))
        self.assertEqual([r["claim_id"] for r in rows], ["claim_1", "claim_0"])
        self.assertEqual([r["status"] for r in rows], ["verified", "withdrawn"])
        self.assertEqual(rows[0]["points"], 25)
        self.assertEqual(rows[1]["points"], 0)

    def test_strike_penalty_floors_at_zero(self):
        claim_id = t.verified_claim(self.c, ref="3")
        t.challenge(self.c, claim_id)
        t.resolve(self.c, claim_id, t.MODEL_UNSUPPORTED)
        self.assertEqual(self.c.get_score(t.OWNER), 0)
        self.assertEqual(json.loads(self.c.get_profile(t.OWNER))["earned"], 0)

    def test_strikes_reduce_other_earned_points(self):
        good = t.verified_claim(self.c, ref="1", statement="Maintained the widgets release process")
        t.verify(self.c, t.post(self.c, kind="release", ref="v1.0.0"))
        bad = t.post(self.c, ref="5")
        t.verify(self.c, bad)
        t.challenge(self.c, bad)
        t.resolve(self.c, bad, t.MODEL_UNSUPPORTED)
        profile = json.loads(self.c.get_profile(t.OWNER))
        self.assertEqual(profile["earned"], 25 + 30)
        self.assertEqual(profile["score"], 25 + 30 - 25)
        self.assertEqual(profile["counts"]["overturned"], 1)
        self.assertEqual(profile["counts"]["verified"], 2)
        self.assertEqual(profile["bonded"], str(2 * t.BOND))
        self.assertTrue(good)


class TestProfileAndLists(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()
        t.bind(self.c)

    def test_profile_shape(self):
        claim_id = t.post(self.c)
        t.verify(self.c, claim_id)
        profile = json.loads(self.c.get_profile(t.OWNER.upper().replace("0X", "0x")))
        self.assertEqual(profile["address"], t.OWNER)
        self.assertEqual(profile["login"], "octodev")
        self.assertEqual(profile["badge"], "BRONZE")
        self.assertEqual(profile["next_badge"], {"name": "SILVER", "at": 60})
        self.assertEqual(profile["skills"], {"python": 25, "sorting": 25})
        self.assertEqual(profile["open_challenges"], 0)
        self.assertTrue(profile["verified"])
        self.assertEqual(len(profile["claims"]), 1)

    def test_profile_open_challenge_and_pending_balance(self):
        claim_id = t.verified_claim(self.c)
        t.challenge(self.c, claim_id)
        profile = json.loads(self.c.get_profile(t.OWNER))
        self.assertEqual(profile["open_challenges"], 1)
        self.assertEqual(json.loads(self.c.get_profile(t.CHALLENGER))["pending_withdrawal"], "0")

    def test_list_claims_pagination_newest_first(self):
        for n in range(1, 6):
            t.post(self.c, ref=str(n))
        page = json.loads(self.c.list_claims(0, 2))
        self.assertEqual(page["total"], 5)
        self.assertEqual([r["claim_id"] for r in page["claims"]], ["claim_4", "claim_3"])
        page = json.loads(self.c.list_claims(4, 10))
        self.assertEqual([r["claim_id"] for r in page["claims"]], ["claim_0"])
        self.assertEqual(json.loads(self.c.list_claims(99, 10))["claims"], [])
        self.assertEqual(len(json.loads(self.c.list_claims(0, 9999))["claims"]), 5)

    def test_get_claim_unknown(self):
        t.expect_user_error(self, self.c.get_claim, "claim_404")

    def test_constants_view(self):
        data = json.loads(self.c.get_constants())
        self.assertEqual(data["slash_bps"], 8000)
        self.assertEqual(data["challenger_share_bps"], 7500)
        self.assertEqual(data["kind_points"], {"commit": 10, "pull_request": 20, "release": 30})
        self.assertEqual(data["badges"][0], [400, "PLATINUM"])


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.c = t.make_contract()
        t.bind(self.c)

    def test_event_sequence_for_a_full_story(self):
        claim_id = t.post(self.c)
        t.verify(self.c, claim_id)
        t.challenge(self.c, claim_id)
        t.resolve(self.c, claim_id, t.MODEL_SUPPORTED)
        t.CLOCK.advance(t.SkillBond.CHALLENGE_WINDOW_SECONDS + 1)
        t.set_caller(t.OWNER)
        self.c.release_bond(claim_id)
        ledger = json.loads(self.c.get_ledger(0, 50))
        kinds = [e["type"] for e in reversed(ledger["events"])]
        self.assertEqual(kinds, ["bound", "posted", "verified", "challenged", "dismissed", "finalized"])
        self.assertEqual([e["seq"] for e in ledger["events"]], [5, 4, 3, 2, 1, 0])
        self.assertEqual(ledger["totals"]["claims"], 1)
        self.assertEqual(ledger["totals"]["challenges"], 1)
        self.assertEqual(ledger["totals"]["bound_wallets"], 1)
        self.assertTrue(ledger["accounting"]["solvent"])

    def test_ledger_pagination(self):
        for n in range(1, 4):
            t.post(self.c, ref=str(n))
        page = json.loads(self.c.get_ledger(1, 2))
        self.assertEqual([e["seq"] for e in page["events"]], [2, 1])
        self.assertEqual(page["total_events"], 4)

    def test_stats_and_accounting_views(self):
        t.post(self.c)
        stats = json.loads(self.c.get_stats())
        self.assertEqual(stats["claims"], 1)
        self.assertEqual(stats["locked"], str(t.BOND))
        self.assertEqual(json.loads(self.c.get_accounting())["locked"], str(t.BOND))
        self.assertEqual(self.c.get_contract_balance(), str(t.BOND))


if __name__ == "__main__":
    unittest.main()
