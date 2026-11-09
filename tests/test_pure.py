import unittest

from tests import _bootstrap as t

m = t.m


class TestPureHelpers(unittest.TestCase):
    def test_parse_tags(self):
        self.assertEqual(m._parse_tags("Rust, zk ; c++"), ["rust", "zk", "c++"])
        self.assertEqual(m._parse_tags("a,a,A"), ["a"])
        for bad in ("", " , ", "a,b,c,d", "has space", "x" * 25, "-lead", "ünï"):
            with self.assertRaises(ValueError, msg=bad):
                m._parse_tags(bad)

    def test_evidence_urls(self):
        self.assertEqual(m._evidence_url("commit", "a/b", "c" * 40), "https://api.github.com/repos/a/b/commits/" + "c" * 40)
        self.assertEqual(m._evidence_url("pull_request", "a/b", "9"), "https://api.github.com/repos/a/b/pulls/9")
        self.assertEqual(m._evidence_url("release", "a/b", "v1/x y"), "https://api.github.com/repos/a/b/releases/tags/v1%2Fx%20y")

    def test_counter_url_canonical_form(self):
        ok = "https://API.github.com/repos/a/b/compare/main...feature"
        self.assertEqual(m._canonical_counter_url(ok), "https://api.github.com/repos/a/b/compare/main...feature")
        self.assertEqual(m._canonical_counter_url(""), "")
        self.assertEqual(m._canonical_counter_url("   "), "")
        self.assertIsNone(m._canonical_counter_url("ftp://api.github.com/repos/a/b/commits/x"))
        self.assertIsNone(m._canonical_counter_url("https://api.github.com/repos/a/b/commits/x/../../../user"))
        self.assertIsNone(m._canonical_counter_url("https://api.github.com/repos/a/b/commits/" + "x" * 400))
        self.assertIsNone(m._canonical_counter_url("https://api.github.com/repos/a/b/commits/%2e%2e/%2E%2e/user"))
        self.assertIsNone(m._canonical_counter_url("https://api.github.com/repos/a/b/commits/x%2Fy"))

    def test_size_bonus_and_points(self):
        self.assertEqual([m._size_bonus(n) for n in (0, 19, 20, 299, 300, 10 ** 6)], [0, 0, 5, 5, 10, 10])
        self.assertEqual(m._base_points("commit", 0), 10)
        self.assertEqual(m._base_points("release", 500), 40)
        self.assertEqual(m._base_points("unknown", 500), 10)

    def test_bond_weight(self):
        gen = 10 ** 18
        self.assertEqual([m._bond_weight(n * gen) for n in (1, 9, 10, 99, 100, 999, 1000)], [1, 1, 2, 2, 3, 3, 4])

    def test_count_rejects_bools_and_negatives(self):
        self.assertIsNone(m._count(True))
        self.assertIsNone(m._count(-1))
        self.assertIsNone(m._count("3"))
        self.assertEqual(m._count(3), 3)

    def test_safe_json_obj(self):
        self.assertEqual(m._safe_json_obj({"a": 1}), {"a": 1})
        self.assertEqual(m._safe_json_obj('{"a": 1}'), {"a": 1})
        self.assertEqual(m._safe_json_obj("[1]"), {})
        self.assertEqual(m._safe_json_obj(None), {})

    def test_lenient_json(self):
        self.assertEqual(m._load_json_lenient('xx {"a": 1} yy'), {"a": 1})
        self.assertIsNone(m._load_json_lenient("nothing"))
        self.assertIsNone(m._load_json_lenient(""))


if __name__ == "__main__":
    unittest.main()
