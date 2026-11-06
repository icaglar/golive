---
name: deploy
description: Gets the app running on each app server (staging first, then prod) - a read-only deploy key, the repo cloned into /srv/app, a server-side .env with APP_ENV, APP_TAG, COMPOSE_FILE and generated secrets that never pass through the chat, per-environment compose overrides with memory limits, the pull-deploy systemd unit, and a first start with no public ports except the reverse proxy. Use for the deploy go-live step, or when the user says "uygulamayı sunucuya kur", "deploy et", "repo'yu sunucuya çek", "docker compose ile ayağa kaldır", "staging'i kur".
---

# First deploy

Talk to the user in the language they use. Values from `.claude/golive.yaml`; run this **per app server, staging first, then prod**, and record `steps.deploy.envs.<env>`. Each server is `servers.<name>` (role app); `<name>` and `<ipv4>` below come from there. Every server command: `ssh -i <key> -o IdentitiesOnly=yes -p <ssh_port> <deploy_user>@<ipv4> '…'`.

## 1. Repo side (local)

- The GitHub repo exists (`gh repo view` or the GitHub MCP). If not, offer to create a **private** one (`gh repo create <name> --private --source . --push`); ask first.
- A compose file at the root (`compose.yaml`); note it in `server_defaults.compose_file`. Service names assumed by the templates: `api`, `web`, `worker`, `migrate` (rename or delete in the overrides to match).
- Copy `${CLAUDE_PLUGIN_ROOT}/templates/compose.staging.yaml` and `compose.prod.yaml` into the repo root and adapt them (service names, memory limits). Staging adds its own `db`; prod has none (dedicated DB server). Keep `db` out of the base file, or give it `profiles: ["staging"]`.
- Image lines use `${APP_TAG}` (e.g. `ghcr.io/<owner>/<repo>-web:${APP_TAG}`); `APP_TAG` is `staging` or `prod`.
- Optional `migrate` service in the base file (same image as `api`, command = the migration command, `restart: "no"`); the pull unit runs `docker compose run --rm migrate` before `up` when it exists.
- No `ports:` except the reverse proxy; `restart: unless-stopped`; memory limits (`mem_limit`) so one container cannot trigger the OOM killer (sum under about 75% of RAM).
- `.gitignore` has `.env` and `certs/`; `.env.example` lists every variable, empty.
- Commit and push after the user agrees.

## 2. Deploy key

1. On the server: `ssh-keygen -t ed25519 -N "" -C "<name> deploy" -f ~/.ssh/deploy_key`, print the `.pub`.
2. Add it as a **read-only** deploy key: `gh repo deploy-key add <file> --title "<name>"` (with the user's yes), else the user adds it in GitHub Settings -> Deploy keys.
3. `~/.ssh/config`: `Host github.com` with `IdentityFile ~/.ssh/deploy_key`, `IdentitiesOnly yes`; test with `ssh -o StrictHostKeyChecking=accept-new -T git@github.com`.

## 3. Clone, then configure

1. **Clone first**: `git clone git@github.com:<owner>/<repo>.git /srv/app` (cloud-init left it empty; creating `.env` before the clone makes git refuse).
2. Only then write `/srv/app/.env` (`chmod 600`) from `.env.example`, adding `APP_ENV`, `APP_TAG`, `COMPOSE_FILE`, and generating secrets **in the same command** so values never reach the chat:

   ```bash
   cd /srv/app && cp .env.example .env && chmod 600 .env && \
   PW=$(openssl rand -hex 24) && \
   printf 'APP_ENV=<env>\nAPP_TAG=<env>\nCOMPOSE_FILE=compose.yaml:compose.<env>.yaml\nPOSTGRES_PASSWORD=%s\n' "$PW" >> .env && \
   sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://app:${PW}@db:5432/app|" .env
   ```

   Staging uses `db:5432`. Prod has no local DB: `POSTGRES_PASSWORD` and `DATABASE_URL` are written by the `database` skill when the DB server exists (private IP); until then leave them out. Edit duplicates (`sed` on existing keys) instead of appending twice.
3. Values only the user has (third-party keys): list the names; they fill them in over SSH. Mail settings come in `app_config`.
4. The `.env` holds every generated secret: the `database` skill backs it up offsite (restic); tell the user it is not in git.

## 4. Pull unit (nothing goes live by itself)

Install on the server (replace `__DEPLOY_USER__`): `${CLAUDE_PLUGIN_ROOT}/templates/systemd/golive-pull.sh` -> `/usr/local/bin/golive-pull` (0755); `golive-pull.service` and `golive-pull.timer` -> `/etc/systemd/system/`; `sudo systemctl daemon-reload && sudo systemctl enable --now golive-pull.timer`. The unit follows the git tag `golive-$APP_ENV`, which only `release.yml` creates and moves, runs migrations, `up -d --remove-orphans`, prunes images and writes the `PullFailed` heartbeat. Until that tag exists the unit finds nothing to deploy (expected).

## 5. First start

The tag does not exist before the first release, so start the stack once by hand from the checked-out commit, and tell the user that is why: `cd /srv/app && docker compose pull || true; docker compose up -d --build`, then `docker compose ps` (running/healthy) and `docker compose logs --tail 50`. Check the app answers inside the network (e.g. `docker compose exec -T web wget -qO- http://localhost:3000/ | head -c 200`). After the first `release` run the pull unit takes over.

**Same-server layout** (`environments.layout: same-server`): two stacks on one box, `/srv/app-staging` (`APP_ENV=staging`) and `/srv/app` (prod), each with its own clone, `.env`, `COMPOSE_PROJECT_NAME=<project>-staging` / `<project>-prod` in `.env` (different project names so volumes and networks do not collide), and its own pull unit instance (`WorkingDirectory`/`EnvironmentFile`/`GOLIVE_DIR` pointing at the staging path). One Caddy fronts both (tls skill). Mind the memory sum of both stacks.

The site is not public yet: `tls` adds Caddy, `dns_records` points the domain here. Set `steps.deploy.envs.<env>: done` with the commit that runs.
