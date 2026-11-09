"""
Shared test bootstrap: wires up the offline genlayer SDK stub, loads the
contract once (contract.py by default, or the file named by the
SB_CONTRACT environment variable, which is how the stripped deploy file is
tested), replaces the contract's single clock with a controllable one, and
provides builders for GitHub records and common flows.
"""
import datetime as _dt
import importlib.util
import json as _json
import os
import sys
from unittest.mock import patch as _patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_DIR = os.path.join(_THIS_DIR, "genlayer_stub")
if _STUB_DIR not in sys.path:
    sys.path.insert(0, _STUB_DIR)

CONTRACT_PATH = os.environ.get("SB_CONTRACT") or os.path.join(os.path.dirname(_THIS_DIR), "contract.py")
_spec = importlib.util.spec_from_file_location("skillbond_contract", CONTRACT_PATH)
_contract_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract_module)

m = _contract_module
SkillBond = m.SkillBond
gl = m.gl
Address = m.Address
u256 = m.u256

# Production floors are in whole GEN; tests use small round numbers of wei.
SkillBond.MIN_BOND = 1000
SkillBond.KEEPER_REWARD = 50

UTC = _dt.timezone.utc
BASE = _dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
DAY = 86400


class Clock:
    def __init__(self):
        self.now = BASE

    def reset(self):
        self.now = BASE

    def set(self, moment):
        self.now = moment

    def advance(self, seconds):
        self.now = self.now + _dt.timedelta(seconds=seconds)


CLOCK = Clock()
SkillBond._now_utc = staticmethod(lambda: CLOCK.now)

OWNER = "0x" + "11" * 20
CHALLENGER = "0x" + "22" * 20
KEEPER = "0x" + "33" * 20
STRANGER = "0x" + "44" * 20
SECOND_OWNER = "0x" + "55" * 20

LOGIN = "OctoDev"
REPO = "acme/widgets"
SHA = "a" * 40
BOND = 10000
STATEMENT = "Built the sorting engine for the widgets library"
TAGS = "python,sorting"


def make_contract():
    CLOCK.reset()
    reset_transfers()
    return SkillBond()


def set_caller(address_str):
    gl.message.sender_address = Address(address_str)


def reset_transfers():
    gl.evm.transfers.clear()


class PaymentRejected(gl.vm.UserError):
    """Raised by call_payable when a payable call was rejected and the GEN
    was credited back to the sender's withdrawable balance."""


def _snapshot(c):
    return (dict(c.claims), int(c.claim_count), dict(c.logins), dict(c.evidence_index), int(c.locked_total),
            int(c.pool), int(c.event_count))


def pending(c, address):
    return int(c.get_pending_withdrawal(address))


def call_payable(c, method_name, value, *args, **kwargs):
    gl.message.value = u256(value)
    c.balance = c.balance + u256(value)
    sender = str(gl.message.sender_address).lower()
    before = _snapshot(c)
    owed_before = pending(c, sender)
    try:
        result = getattr(c, method_name)(*args, **kwargs)
    except Exception:
        c.balance = c.balance - u256(value)
        raise
    finally:
        gl.message.value = u256(0)
    if isinstance(result, str) and result.startswith('{"refunded_wei"') or (
            isinstance(result, str) and '"rejected"' in result and '"refunded_wei"' in result):
        data = _json.loads(result)
        assert data["refunded_wei"] == str(int(value)), data
        assert pending(c, sender) - owed_before == int(value)
        assert _snapshot(c) == before, "a rejected payable call changed state"
        raise PaymentRejected(data["rejected"])
    return result


def do_withdraw(c, address):
    set_caller(address)
    before = len(gl.evm.transfers)
    c.withdraw()
    paid = sum(int(t["value"]) for t in gl.evm.transfers[before:])
    c.balance = c.balance - u256(paid)
    return paid


def accounting(c):
    return _json.loads(c.get_accounting())


def assert_accounting(testcase, c):
    a = accounting(c)
    owed = int(a["locked"]) + int(a["pending_withdrawals"]) + int(a["pool"])
    testcase.assertEqual(int(a["contract_balance"]), owed, a)
    testcase.assertTrue(a["solvent"])


def iso(moment):
    return moment.isoformat()


def gh_ts(epoch):
    return _dt.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


BASE_EPOCH = int(BASE.timestamp())


def api(path):
    return "https://api.github.com" + path


def gist_url(gist_id):
    return api("/gists/" + gist_id)


def pr_url(number=7, repo=REPO):
    return api(f"/repos/{repo}/pulls/{number}")


def commit_url(sha=SHA, repo=REPO):
    return api(f"/repos/{repo}/commits/{sha}")


def release_url(tag="v1.0.0", repo=REPO):
    return api(f"/repos/{repo}/releases/tags/{tag}")


def repo_meta_url(repo=REPO):
    return api(f"/repos/{repo}")


def compare_url(sha=SHA, repo=REPO, branch="main"):
    return api(f"/repos/{repo}/compare/{branch}...{sha}")


def gist_json(owner=LOGIN, address=OWNER, content=None):
    text = content if content is not None else f"skillbond:{address.lower()}"
    return {"owner": {"login": owner}, "files": {"proof.txt": {"content": text}}}


def pr_json(number=7, login=LOGIN, repo=REPO, **over):
    data = {
        "number": number, "state": "closed", "merged": True, "merged_at": gh_ts(BASE_EPOCH - DAY),
        "title": "Add widget sorting", "body": "Implements a stable merge sort for widgets.",
        "user": {"login": login}, "base": {"repo": {"full_name": repo}, "ref": "main"},
        "additions": 120, "deletions": 8,
    }
    for key, value in over.items():
        if value is KeyError:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def commit_json(sha=SHA, login=LOGIN, repo=REPO, **over):
    data = {
        "sha": sha, "html_url": f"https://github.com/{repo}/commit/{sha}",
        "author": {"login": login} if login else None,
        "commit": {"message": "Implement stable sort", "author": {"date": gh_ts(BASE_EPOCH - DAY)}},
        "stats": {"total": 42, "additions": 40, "deletions": 2},
        "files": [{"filename": "src/sort.py"}, {"filename": "tests/test_sort.py"}],
    }
    data.update(over)
    return data


def release_json(tag="v1.0.0", login=LOGIN, repo=REPO, **over):
    data = {
        "tag_name": tag, "name": "Widgets 1.0", "body": "First stable release with sorting.",
        "draft": False, "prerelease": False, "author": {"login": login}, "published_at": gh_ts(BASE_EPOCH - DAY),
        "html_url": f"https://github.com/{repo}/releases/tag/{tag}",
    }
    data.update(over)
    return data


def commit_pages(sha=SHA, repo=REPO, login=LOGIN, status="behind", branch="main", **over):
    return {
        commit_url(sha, repo): commit_json(sha, login, repo, **over),
        repo_meta_url(repo): {"default_branch": branch},
        compare_url(sha, repo, branch): {"status": status},
    }


def pr_pages(number=7, repo=REPO, login=LOGIN, **over):
    return {pr_url(number, repo): pr_json(number, login, repo, **over)}


def release_pages(tag="v1.0.0", repo=REPO, login=LOGIN, **over):
    return {release_url(tag, repo): release_json(tag, login, repo, **over)}


def web_for(pages):
    def render(url, mode="text"):
        value = pages.get(url)
        if value is None:
            raise RuntimeError("404")
        return value if isinstance(value, str) else _json.dumps(value)
    return render


MODEL_SUPPORTED = {"verdict": "SUPPORTED", "reasoning": "the evidence matches the statement"}
MODEL_UNSUPPORTED = {"verdict": "UNSUPPORTED", "reasoning": "the claim overstates the evidence"}
MODEL_UNDETERMINED = {"verdict": "UNDETERMINED", "reasoning": "too little evidence"}


def run_with(fn, pages, model=None, prompts=None):
    calls = prompts if prompts is not None else []

    def exec_prompt(prompt, response_format="json"):
        calls.append(prompt)
        if model is None:
            raise AssertionError("the model must not be called here")
        if isinstance(model, Exception):
            raise model
        return model

    with _patch.object(gl.nondet.web, "render", side_effect=web_for(pages)), \
            _patch.object(gl.nondet, "exec_prompt", side_effect=exec_prompt):
        return fn()


def bind(c, owner=OWNER, login=LOGIN, gist="abc12345abc12345"):
    set_caller(owner)
    pages = {gist_url(gist): gist_json(login, owner)}
    return run_with(lambda: c.bind_github(login, gist), pages)


def post(c, kind="pull_request", repo=REPO, ref="7", statement=STATEMENT, tags=TAGS, bond=BOND, owner=OWNER):
    set_caller(owner)
    return _json.loads(call_payable(c, "post_claim", bond, kind, repo, ref, statement, tags))["claim_id"]


def get(c, claim_id):
    return _json.loads(c.get_claim(claim_id))


def verify(c, claim_id, pages=None, model=MODEL_SUPPORTED, caller=KEEPER, prompts=None):
    set_caller(caller)
    claim = get(c, claim_id)
    if pages is None:
        if claim["kind"] == "pull_request":
            pages = pr_pages(int(claim["ref"]), claim["repo"], claim["login"])
        elif claim["kind"] == "commit":
            pages = commit_pages(claim["ref"], claim["repo"], claim["login"])
        else:
            pages = release_pages(claim["ref"], claim["repo"], claim["login"])
    return run_with(lambda: c.verify_claim(claim_id), pages, model, prompts)


def verified_claim(c, owner=OWNER, bond=BOND, **post_args):
    bind_if_needed(c, owner)
    claim_id = post(c, owner=owner, bond=bond, **post_args)
    verify(c, claim_id)
    return claim_id


def bind_if_needed(c, owner=OWNER):
    if not c.get_login(owner):
        bind(c, owner, LOGIN, gist="e" + owner[2:10] * 2)


def challenge(c, claim_id, stake=None, challenger=CHALLENGER, allegation="The work was copied from another project", counter=""):
    claim = get(c, claim_id)
    stake = stake if stake is not None else (int(claim["bond"]) + 1) // 2
    set_caller(challenger)
    return call_payable(c, "challenge_claim", stake, claim_id, allegation, counter)


def resolve(c, claim_id, model, pages=None, caller=KEEPER, prompts=None):
    set_caller(caller)
    claim = get(c, claim_id)
    if pages is None:
        pages = pr_pages(int(claim["ref"]), claim["repo"], claim["login"]) if claim["kind"] == "pull_request" else {}
    return run_with(lambda: c.resolve_challenge(claim_id), pages, model, prompts)


def expect_user_error(testcase, fn, *args, **kwargs):
    with testcase.assertRaises(gl.vm.UserError) as ctx:
        fn(*args, **kwargs)
    return str(ctx.exception)
