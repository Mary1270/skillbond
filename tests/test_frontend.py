import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
CONTRACT = open(os.path.join(ROOT, "contract.py"), encoding="utf-8").read()


def contract_methods():
    tree = ast.parse(CONTRACT)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SkillBond")
    return {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}


def script():
    return re.search(r'<script type="module">(.*?)</script>', HTML, re.S).group(1)


class TestFrontend(unittest.TestCase):
    def test_single_file_with_esm_sh_latest(self):
        self.assertIn('from "https://esm.sh/genlayer-js@latest"', HTML)
        self.assertIn('from "https://esm.sh/genlayer-js@latest/chains"', HTML)
        self.assertEqual(len(re.findall(r"<script\b", HTML)), 1)

    def test_clients_use_only_chain_and_account(self):
        for body in re.findall(r"createClient\(\{([^}]*)\}\)", HTML):
            self.assertTrue(body.strip().startswith("chain: studionet"), body)
            self.assertNotIn("provider", body)
        for forbidden in ("initializeConsensusSmartContract", ".connect(", "provider:"):
            self.assertNotIn(forbidden, script())

    def test_hash_routes_exist(self):
        for route in ('href="#/"', 'href="#/new"', 'href="#/profile"', 'href="#/ledger"', 'href="#/guide"',
                      'href="#/integrate"', '"#/claim/"'):
            self.assertIn(route, HTML)
        self.assertIn('addEventListener("hashchange", route)', HTML)

    def test_explore_uses_list_view_not_manual_id_lookup(self):
        self.assertIn('"list_claims"', HTML)
        self.assertIn('"get_stats"', HTML)

    def test_every_called_method_exists_in_the_contract(self):
        js = script()
        called = set(re.findall(r'(?:read|readJson)\("([a-z_]+)"', js))
        called |= set(re.findall(r'write\("[^"]*",\s*"([a-z_]+)"', js))
        called |= set(re.findall(r'\["(get_[a-z_]+|is_verified|has_skill)",\s*\[', js))
        self.assertGreaterEqual(len(called), 14)
        self.assertEqual(called - contract_methods(), set())

    def test_every_write_method_is_reachable_from_the_ui(self):
        used = set(re.findall(r'"([a-z_]+)"', script()))
        for name in ("bind_github", "post_claim", "withdraw_claim", "verify_claim", "challenge_claim", "resolve_challenge",
                     "void_challenge", "release_bond", "withdraw"):
            self.assertIn(name, used)

    def test_contract_data_is_never_inserted_as_html(self):
        js = script()
        self.assertEqual(len(re.findall(r"innerHTML", js)), 1)

    def test_default_contract_address_is_configurable(self):
        self.assertIn("DEFAULT_CONTRACT_ADDRESS", HTML)
        self.assertIn("?contract=", HTML + "?contract=")

    def test_integer_gen_values_only(self):
        self.assertIn("Number.isInteger(n)", script())


if __name__ == "__main__":
    unittest.main()
