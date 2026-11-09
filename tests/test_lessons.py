import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = open(os.path.join(ROOT, "contract.py"), encoding="utf-8").read()
TREE = ast.parse(SOURCE)


def contract_class():
    return next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "SkillBond")


class TestGenVmLessons(unittest.TestCase):
    def test_two_header_lines(self):
        lines = SOURCE.splitlines()
        self.assertEqual(lines[0], "# v0.2.16")
        self.assertTrue(lines[1].startswith('# { "Depends": "py-genlayer:'))
        self.assertEqual(lines[2], "from genlayer import *")

    def test_storage_fields_are_class_annotations_and_never_assigned_a_literal(self):
        cls = contract_class()
        annotated = {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
        for node in ast.walk(init):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in annotated:
                        self.assertNotIsInstance(node.value, (ast.Dict, ast.List, ast.Set), target.attr)
                        ann = next(n.annotation for n in cls.body if isinstance(n, ast.AnnAssign) and n.target.id == target.attr)
                        self.assertNotIn("TreeMap", ast.dump(ann))
                        self.assertNotIn("DynArray", ast.dump(ann))

    def test_no_dot_get_on_storage_maps(self):
        cls = contract_class()
        maps = {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and "TreeMap" in ast.dump(n.annotation)}
        for node in ast.walk(cls):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("get", "pop", "setdefault"):
                value = node.func.value
                if isinstance(value, ast.Attribute) and value.attr in maps:
                    self.fail(f"{value.attr}.{node.func.attr}() on a storage map at line {node.lineno}")

    def test_no_deletion_from_storage_maps(self):
        for node in ast.walk(TREE):
            self.assertNotIsInstance(node, ast.Delete)

    def test_nondet_closures_never_capture_self(self):
        for node in ast.walk(TREE):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_nondet_unsafe":
                self.assertEqual(len(node.args), 2)
                self.assertEqual(node.keywords, [])
                for arg in node.args:
                    names = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}
                    self.assertNotIn("self", names)

    def test_module_level_nondet_helpers_only_call_module_level_names(self):
        for node in TREE.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("_verify_compute", "_gist_compute", "_gather", "_fetch"):
                names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                self.assertNotIn("self", names, node.name)

    def test_validators_read_return_calldata(self):
        self.assertEqual(SOURCE.count("leader_result.calldata"), 2)
        self.assertIsNone(re.search(r"\.value\b", re.sub(r"gl\.message\.value", "", SOURCE)))

    def test_no_datetime_min_and_no_naive_now(self):
        self.assertNotIn("datetime.min", SOURCE)
        self.assertEqual(SOURCE.count("datetime.datetime.now("), 1)

    def test_every_write_method_is_decorated_and_payable_ones_validate_before_writing(self):
        cls = contract_class()
        payable = [n for n in cls.body if isinstance(n, ast.FunctionDef) and any("payable" in ast.dump(d) for d in n.decorator_list)]
        self.assertEqual({n.name for n in payable}, {"post_claim", "challenge_claim"})
        for fn in payable:
            self.assertIn("_bounce", ast.dump(fn))

    def test_all_money_leaves_only_through_withdraw(self):
        self.assertEqual(SOURCE.count("emit_transfer"), 1)
        self.assertEqual(SOURCE.count("_Payee("), 1)

    def test_evidence_host_is_the_only_network_host(self):
        hosts = set(re.findall(r"https?://([a-zA-Z0-9.{}_-]+)", SOURCE))
        self.assertTrue(hosts <= {"{EVIDENCE_HOST}", "{EVIDENCE_HOST}{path}", "api.github.com"}, hosts)
        self.assertEqual(SOURCE.count("gl.nondet.web.render"), 1)


if __name__ == "__main__":
    unittest.main()
