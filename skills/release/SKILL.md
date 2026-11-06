---
name: release
description: Releases a commit to production, always after asking - reads what staging and production run from the golive-staging / golive-prod git tags (or the k8s overlays), shows what changed and any migrations, asks for a yes, then dispatches the release workflow with the full commit sha, follows it and checks the site. Also rolls back to an older commit the same way. Use when the user says "prod'a al", "canlıya çıkar", "staging'i prod'a taşı", "release yap", "geri al", "rollback".
---

# Release to production

Talk to the user in the language they use. Never dispatch a production release without an explicit yes in this conversation. The guard hook also asks before a production release: that prompt is expected.

1. **What runs where** (never from `gh run list` headSha: dispatched runs report main's HEAD, not the released commit):
   - Compose: `git ls-remote --tags origin 'golive-*'` gives the commits behind `golive-staging` and `golive-prod`.
   - k8s: the `sha-<commit>` pins in `deploy/k8s/overlays/staging/kustomization.yaml` and `.../prod/kustomization.yaml`.
   - Release runs are findable by their run-name `release <env> <sha>` (`gh run list --workflow release.yml --json displayTitle,conclusion,createdAt`).
2. **Candidate**:
   - With staging: the commit running on staging (`golive-staging`).
   - Prod-only (`environments.layout: prod-only`): the latest green `ci` run on main (`gh run list --workflow ci.yml --branch main --status success --limit 1 --json headSha`); its `headSha` is the candidate.
   - Rollback: an older commit that was released to prod before (earlier `release prod <sha>` runs) and whose images still exist.
3. **Show the difference**: `git log --oneline <prod sha>..<candidate>` (at most ~15 lines) and the migration files changed in that range (`git diff --name-only <prod>..<candidate>`, look for `migrations/`, `alembic`, `prisma`, `*.sql`). Flag migrations explicitly: they run automatically and may not be reversible.
4. **Ask**: "Release `<short sha>` (N commits, migrations: yes/no) to production?" yes/no. On no, stop.
5. **Dispatch** after the yes with the **full 40-character sha** (`git rev-parse <sha>`): GitHub MCP `actions_run_trigger`, or `gh workflow run release.yml -f environment=production -f sha=<40-char sha>`. Expect the guard prompt.
6. **Follow** the run (`gh run watch`, or `actions_get`); on failure read the failed job's log and explain it in one or two lines.
7. **Check**:
   - Compose: the server's pull unit picks the moved tag up within ~2 minutes: `ssh ... 'sudo journalctl -u golive-pull -n 30 --no-pager'` shows the checkout, migration and `up -d`; `golive_pull_last_success_timestamp_seconds` is fresh.
   - k8s: `flux reconcile kustomization migrate-prod` then `app-prod`, `kubectl rollout status`.
   - Then `curl -sSI https://<domain>` and the health endpoint if there is one. Report in one line.

**Rollback** is the same flow with an older sha. Say plainly that migrations are not undone: if the old code cannot run on the new schema, a forward fix is needed.
