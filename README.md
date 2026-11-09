# SkillBond

Portable, bonded developer reputation, built as a GenLayer Intelligent Contract with a full web frontend.

A developer binds a wallet to a GitHub login, posts **skill claims** ("I shipped X in repo Y") and backs each one with a GEN bond. GenLayer validators read the GitHub evidence (commit, pull request or release), check authorship in code and judge whether the evidence really supports the statement. Verified claims earn score, skill points and badges. Anyone can **challenge** a verified claim by staking GEN. A false claim loses most of its bond.

SkillBond is infrastructure, not a one-off flow: other contracts read reputation through a small read-only API.

## Why it is trustworthy

- **Identity is proven, not typed.** A wallet is bound to a GitHub login by a public gist containing `skillbond:<wallet address>`. Validators fetch the gist from `api.github.com`, and it must be owned by that login. One login maps to one wallet.
- **Authorship is checked in code.** The model never decides who wrote something. Pull request author, commit author or release publisher must equal the bound login, the evidence must belong to the claimed repository, and a pull request must be merged.
- **No fork trick.** A commit must sit in the default-branch history of the claimed repository (checked with the GitHub compare API). A commit that only exists in a fork or an unmerged branch is rejected.
- **The model only judges meaning.** If code facts pass, the model decides whether the statement is supported without overstating the work. A model failure or an "undetermined" answer never records anything: the call reverts and can be retried.
- **Validators agree on structure.** Leader and validators must produce the same verdict and the same extracted facts (author, id, size, date, default-branch relation). Free-text reasoning may differ.
- **Evidence is unique.** One piece of evidence can back one active claim.
- **Only GitHub's API host is ever fetched.** Counter-evidence URLs are restricted to `https://api.github.com/repos/...` paths without query, port, credentials or path traversal.

## Lifecycle

| Status | Meaning | Who can act |
| --- | --- | --- |
| pending | Posted, bond locked | anyone: `verify_claim`; claimant: `withdraw_claim` (full refund) |
| verified | Evidence supported, challenge window open | anyone except claimant: `challenge_claim`; claimant after the window: `release_bond` |
| challenged | One open challenge | anyone: `resolve_challenge`; anyone after the deadline: `void_challenge` |
| finalized | Bond released, score permanent | none |
| rejected | Evidence did not support the claim | none |
| overturned | Challenge upheld, bond slashed, strike | none |
| withdrawn | Claimant withdrew before verification | none |

## Bond split rules

| Event | Result |
| --- | --- |
| Verification finds no support | 90% of the bond refunded, 10% to the keeper pool |
| Challenge upheld | 80% of the bond is slashed: 75% of that to the challenger, 25% to the pool. Claimant keeps 20%. Challenger gets the stake back. Claimant gets a strike (-25 score). Evidence becomes claimable again |
| Challenge dismissed | Challenger loses the whole stake: 60% to the claimant, 40% to the pool. Claim gets +5 score |
| Challenge undetermined past the deadline | `void_challenge` refunds the stake; the challenge still counts toward the limit |
| Bond release | Claimant, after the challenge window, with no open challenge |

Minimum challenge stake is half of the bond (rounded up). A claim takes at most 3 challenges, voided ones included, so nobody can keep a bond locked forever. The claimant cannot challenge their own claim. Whoever triggers a rejection or a challenge resolution (and is not a party) earns a small keeper reward, capped by what that same call put into the pool, so the pool cannot be drained by self-verification.

At challenge time the claim is judged on its merits only. If the code facts no longer hold (the repository was renamed or the author changed their GitHub login), the result is undetermined, never a slash: a claim that was true when verified cannot be punished for later changes on GitHub.

## Scoring

`points = (base + size bonus) x bond weight`

| Item | Value |
| --- | --- |
| Base | pull request 20, commit 10, release 30 |
| Size bonus | +5 from 20 changed lines, +10 from 300 |
| Bond weight | x1 below 10 GEN, x2 from 10, x3 from 100, x4 from 1000 |
| Survived challenge | +5 each |
| Strike (overturned claim) | -25 each |

Score is computed on read from the claims, so it can never drift from the data. Points count only for claims made under the GitHub login the wallet is bound to now: an unbound wallet scores 0, and strikes always count. Badges: Bronze 20, Silver 60, Gold 150, Platinum 400. `is_verified` means a bound login and score of at least 10.

## Read-only API for other contracts

| Function | Returns |
| --- | --- |
| `get_score(address)` | int |
| `is_verified(address)` | bool |
| `is_verified_at_least(address, min_score)` | bool |
| `get_skill_score(address, tag)` | int |
| `has_skill(address, tag, min_points)` | bool |
| `get_badge(address)` | `NONE`, `BRONZE`, `SILVER`, `GOLD`, `PLATINUM` |
| `get_claims(address)` | JSON list of the wallet's claims |
| `get_profile(address)` | JSON: score, badge, skills, strikes, claims |
| `get_login(address)`, `get_address_for_login(login)` | binding, both directions |
| `get_ledger(offset, limit)` | JSON: event log, totals, GEN accounting |
| `get_claim(id)`, `list_claims(offset, limit)`, `get_stats()`, `get_constants()`, `get_accounting()` | JSON |

```python
bond = gl.get_contract_at(Address(SKILLBOND)).view()
if not bond.has_skill(who, "rust", 40):
    raise gl.vm.UserError("Needs 40+ verified Rust points")
```

## Money safety

- All GEN leaves through one pull-payment `withdraw()` (balance zeroed before the transfer).
- Payable calls validate before writing. A rejected call with GEN attached is refunded to the sender's withdrawable balance instead of reverting, so GEN can never be stranded.
- Every wei is accounted: `contract balance = locked + owed to wallets + pool`. `get_accounting` exposes it and the test suite checks the invariant after every step of randomized runs (value in = value out + pool).
- No owner, no admin keys, no upgrade path. Constants are fixed in the contract.

## Frontend

`index.html` is a single file (genlayer-js from esm.sh), mobile first, with hash routing:

| Route | Purpose |
| --- | --- |
| `#/` | Explore: stats, status filters, search, claim cards |
| `#/claim/<id>` | Status stepper, role banner, only the actions you may take, the rules in this claim's numbers |
| `#/new` | Three-step guided posting: wallet, GitHub binding (copyable gist line), claim form with smart URL paste |
| `#/profile/<address>` | Score ring, badge, skills, strikes, claims, withdraw |
| `#/ledger` | GEN accounting, rules, paged event timeline |
| `#/guide` | Test path with live ticks and failure-path checklist |
| `#/integrate` | API reference, snippet, live read playground |

The wallet sheet can create up to five throwaway test wallets (Wallet A, B, ...) inside the browser tab, switch between them and request test GEN, so every role can be tested from one phone.

Set the deployed address in `index.html` (`DEFAULT_CONTRACT_ADDRESS`) or open the page with `?contract=0x...`.

## Files

| File | Purpose |
| --- | --- |
| `contract.py` | Documented contract source |
| `contract_deploy.py` | Two header lines, then code only. Paste this into GenLayer Studio |
| `contract_testnet_deploy.py` | Same code with a 3 minute challenge window and 5 minute resolution timeout, for live tests |
| `tools/make_deploy.py`, `tools/make_testnet_deploy.py` | Build the two files above; CI fails if they are stale |
| `tests/` | 150+ offline tests with a stub of the GenLayer SDK |
| `index.html` | Frontend |

## Tests

```
python3 -m unittest discover -s tests -t .
SB_CONTRACT=$PWD/contract_deploy.py python3 -m unittest discover -s tests -t .
```

The suite covers identity binding, claim validation, every verification path (code rejections, model verdicts, fetch failures, consensus disagreement), challenge splits to the wei, voiding, bond release, composable views, pagination, the ledger, randomized accounting invariants, GenVM lessons (storage rules, no `self` in non-deterministic closures) and frontend consistency.

Offline tests use a stub SDK and fake GitHub responses. They do not prove live validator behaviour; see the live test path in the app.

## Limitations

- A very large commit record can exceed what a page fetch returns and will be unreadable; use a pull request claim instead.
- Unauthenticated GitHub API rate limits can make verification retry.
- Reputation is bond-weighted: more GEN buys a higher multiplier, but only for real, verified work.

MIT licensed.
