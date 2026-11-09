import json
import random
import unittest

from tests import _bootstrap as t

ACTORS = [t.OWNER, t.SECOND_OWNER, t.CHALLENGER, t.KEEPER, t.STRANGER]


class TestAccountingInvariant(unittest.TestCase):
    """Every wei in the contract is either locked in a claim or challenge,
    owed in a withdrawable balance, or in the pool. Random operation
    sequences must never break that, and everyone can always withdraw."""

    def run_random(self, seed, steps=70):
        rng = random.Random(seed)
        c = t.make_contract()
        t.bind(c, t.OWNER, "OctoDev", gist="aaaa1111")
        t.bind(c, t.SECOND_OWNER, "Second", gist="bbbb2222")
        ledger = {"in": 0, "out": 0}
        ref = 0

        def pay_in(method, value, *args):
            try:
                t.call_payable(c, method, value, *args)
            except t.PaymentRejected:
                ledger["in"] += value
                raise
            ledger["in"] += value

        def pay_out(actor):
            ledger["out"] += t.do_withdraw(c, actor)
        for _ in range(steps):
            ids = [f"claim_{i}" for i in range(int(c.claim_count))]
            action = rng.choice(["post", "post", "verify", "verify", "challenge", "resolve", "withdraw_claim",
                                 "release", "void", "advance", "pay"])
            try:
                if action == "post":
                    owner = rng.choice([t.OWNER, t.SECOND_OWNER])
                    login = "OctoDev" if owner == t.OWNER else "Second"
                    ref += 1
                    bond = rng.choice([1000, 2500, 10000, 33333])
                    t.set_caller(owner)
                    pay_in("post_claim", bond, "pull_request", t.REPO, str(ref), t.STATEMENT, t.TAGS)
                elif action == "pay":
                    pay_out(rng.choice(ACTORS))
                elif not ids:
                    continue
                elif action == "advance":
                    t.CLOCK.advance(rng.choice([60, 86400, 4 * 86400]))
                else:
                    claim_id = rng.choice(ids)
                    claim = t.get(c, claim_id)
                    if action == "verify":
                        login = claim["login"]
                        model = rng.choice([t.MODEL_SUPPORTED, t.MODEL_SUPPORTED, t.MODEL_UNSUPPORTED])
                        t.verify(c, claim_id, pages=t.pr_pages(int(claim["ref"]), claim["repo"], login), model=model,
                                 caller=rng.choice(ACTORS))
                    elif action == "challenge":
                        stake = (int(claim["bond"]) + 1) // 2 + rng.choice([0, 0, 7])
                        t.set_caller(rng.choice(ACTORS))
                        pay_in("challenge_claim", stake, claim_id, "The work was copied from elsewhere", "")
                    elif action == "resolve":
                        model = rng.choice([t.MODEL_SUPPORTED, t.MODEL_UNSUPPORTED])
                        t.resolve(c, claim_id, model, pages=t.pr_pages(int(claim["ref"]), claim["repo"], claim["login"]),
                                  caller=rng.choice(ACTORS))
                    elif action == "withdraw_claim":
                        t.set_caller(claim["owner"])
                        c.withdraw_claim(claim_id)
                    elif action == "release":
                        t.set_caller(claim["owner"])
                        c.release_bond(claim_id)
                    elif action == "void":
                        t.set_caller(rng.choice(ACTORS))
                        c.void_challenge(claim_id)
            except (t.gl.vm.UserError, t.PaymentRejected):
                pass
            t.assert_accounting(self, c)
            for claim_id in [f"claim_{i}" for i in range(int(c.claim_count))]:
                claim = t.get(c, claim_id)
                self.assertGreaterEqual(int(claim["bond"]), t.SkillBond.MIN_BOND)
        for claim_id in [f"claim_{i}" for i in range(int(c.claim_count))]:
            claim = t.get(c, claim_id)
            if claim["status"] == "challenged":
                t.CLOCK.advance(10 * 86400)
                t.set_caller(t.STRANGER)
                c.void_challenge(claim_id)
        for claim_id in [f"claim_{i}" for i in range(int(c.claim_count))]:
            claim = t.get(c, claim_id)
            if claim["status"] == "verified":
                t.CLOCK.advance(10 * 86400)
                t.set_caller(claim["owner"])
                c.release_bond(claim_id)
            elif claim["status"] == "pending":
                t.set_caller(claim["owner"])
                c.withdraw_claim(claim_id)
        self.assertEqual(int(c.locked_total), 0)
        for actor in ACTORS:
            if t.pending(c, actor):
                pay_out(actor)
        pool = int(c.pool)
        self.assertEqual(int(c.balance), pool)
        self.assertEqual(int(c.pending_total), 0)
        return ledger["in"], ledger["out"], pool

    def test_invariant_over_many_random_runs(self):
        for seed in range(40):
            with self.subTest(seed=seed):
                deposits, paid, pool = self.run_random(seed)
                self.assertEqual(deposits, paid + pool)

    def test_value_conservation(self):
        for seed in range(100, 140):
            with self.subTest(seed=seed):
                deposits, paid, pool = self.run_random(seed)
                self.assertEqual(deposits, paid + pool)


if __name__ == "__main__":
    unittest.main()
