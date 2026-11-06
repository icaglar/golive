# golive: protect `main`

`main` deploys to staging automatically, so it must only receive code that passed `ci`. Requires admin on the
repo; the `ci` check name comes from the job `ci` in `.github/workflows/ci.yml` (it must have run once so
GitHub knows it). Replace `{owner}/{repo}`. Run only after the user's yes (it changes repository settings).

Check plan support first: branch protection on private repos needs GitHub Pro/Team/Enterprise (check the
GitHub docs for the current plan matrix). On a plan without it, tell the user and skip.

## Payload (`branch-protection.json`)

```json
{
  "required_status_checks": {"strict": true, "contexts": ["ci"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
```

- `required_pull_request_reviews`: `null` suits a solo owner. With a team (and a plan that supports it) use
  `{"required_approving_review_count": 1, "dismiss_stale_reviews": true}`.
- `enforce_admins: false` lets the owner merge in an emergency; set `true` once a second admin exists.

## Apply

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input branch-protection.json
```

Verify: `gh api repos/{owner}/{repo}/branches/main/protection --jq '.required_status_checks.contexts'`

## Interactions to know

- k8s runtime: `release.yml` commits the image pin to `main` (or `GOLIVE_DEPLOY_BRANCH`). A required status
  check blocks that direct push, so either let `github-actions` bypass (a repository ruleset with a bypass
  actor replaces this protection call on plans that have rulesets) or point Flux at a deploy branch.
- Compose runtime: `release.yml` only moves tags `golive-staging` / `golive-prod`; branch protection does not
  affect it. If a tag ruleset blocks force-updating `golive-*`, allow github-actions to bypass it.
