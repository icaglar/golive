---
name: workflows
description: Creates the GitHub Actions CI/CD for the app after asking the user what they want - tests, image build and scan on every PR, automatic release to staging on main, a manual confirmed release to production - with actions pinned to commit SHAs, Dependabot and branch protection; for Docker Compose (git tag + pull timer on the server) or k8s (overlay sha pin + Flux). Use for the ci_cd go-live step, or when the user says "workflow oluştur", "CI/CD kur", "GitHub Actions", "otomatik deploy", "staging'e otomatik çıksın", "branch protection".
---

# CI/CD workflows

Talk to the user in the language they use. Read `runtime`, `environments` (layout) and `profile.github` from `.claude/golive.yaml`. Templates: `${CLAUDE_PLUGIN_ROOT}/templates/workflows/` and `${CLAUDE_PLUGIN_ROOT}/templates/github/`. The release model: prod changes only when `release.yml` runs for production, which the `release` skill starts after the user's yes. Nothing deploys on a push to prod.

## 1. Ask first

Look at the repo (test commands, Dockerfiles), then one `AskUserQuestion` form, best guess first:

1. **What to create** (multi-select): tests, build and image scan on PRs and main; automatic release to staging on main (only with a staging environment); manual release to production. Recommend all that apply.
2. **Test command**: what you found, or "no tests yet" (the job just builds).
3. **Production approval**:
   - **Claude asks, then dispatches** (recommended): the `release` skill shows what changes, asks, then runs `release.yml`.
   - **GitHub required reviewers** on a `production` environment: only public repos, or private repos on Enterprise.
   - **Tag-based**: `v*` tags trigger the release with `environment: production` and `sha: ${{ github.sha }}`.

## 2. Generate

- `ci.yml`: replace `__TEST_COMMAND__`; the build matrix gets one entry per service with its Dockerfile (`service`, `context`). Prod-only or no automatic staging: **delete the STAGING-ONLY job**.
- `release.yml`: set `SERVICES` (space separated, same names). Required reviewers: uncomment `environment:`.
- **Pin every `uses:` to the full commit SHA** and keep the tag as a comment: `uses: actions/checkout@<40-char sha> # v4`. Look the SHA up with `gh api repos/<owner>/<action>/commits/<tag> --jq .sha` (or `git ls-remote https://github.com/<owner>/<action> <tag>`; for annotated tags use the `^{}` line). The same for the local reusable call: `./.github/workflows/release.yml` stays as is.
- Copy `templates/github/dependabot.yml` to `.github/dependabot.yml`.
- Write to `.github/workflows/`, show the diff, commit and push after a yes.

## 3. Wire it up

- **Variables**: `gh variable set GOLIVE_RUNTIME --body compose` (or `k8s`). On k8s with a protected `main`, also `GOLIVE_DEPLOY_BRANCH` (a deploy branch Flux watches) or let the Actions bot bypass.
- **Branch protection** after the first `ci` run (GitHub only knows the `ci` check then): follow `templates/github/branch-protection.md` (`gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input branch-protection.json`, required check `ci`). Ask first, it changes repo settings. Private repos need a paid plan (`profile.github.plan`; check the GitHub docs): on Free tell the user it is skipped. Org repos: `profile.github.owner_type: org` means the owner is the org slug, and team reviews and rulesets are available on org plans; personal repos use the user's login.
- **Required reviewers** only if chosen: `gh api -X PUT repos/<owner>/<repo>/environments/production` with the reviewer, or the user does it under Settings -> Environments.
- **Compose servers**: nothing to create here. Verify, per server over SSH, that `/srv/app/.env` has `APP_ENV` and `APP_TAG` (written by the `deploy` skill) and that `golive-pull.timer` is active (`systemctl is-active golive-pull.timer`; installed by `deploy` from `templates/systemd/`). If missing, say so and send the user back to the `deploy` step. The server needs `docker login ghcr.io` with a `read:packages` token (user step). CI never connects to the server.
- **k8s**: Flux watches `deploy/k8s/overlays/*` (cluster skill); nothing else to wire.

## 4. First run

Push to main (or `gh workflow run ci.yml`), follow it (`gh run watch`), on failure read `gh run view <id> --log-failed` and explain the cause briefly. Check `https://staging.<domain>` if there is a staging environment.

Set `steps.ci_cd: done` with the workflows created, approval method and whether branch protection is on.
