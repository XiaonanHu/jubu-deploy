# stats.buju.ai — Deployment Guide (Phase 0)

Self-hosted Grafana behind nginx + LetsEncrypt + basic-auth, reading from
Postgres via a read-only role. No third-party services, no PII leaving the VPC.

## What you get

Three dashboards available at `https://stats.buju.ai`:

1. **Live Sessions** — currently active conversations, today's session count,
   distinct kids today, hourly session timeline. 5 s refresh.
2. **Recent Turns** — most recent 200 turns across all conversations,
   filterable by `conversation_id`. **Truncated to 80 chars** until Phase 3
   adds the click-to-reveal + audit-log pattern.
3. **Voice Style — Bandit Scores & Selection Mix** — per-(child, style) score
   table from `child_profiles.preferences`, plus sessions-per-style
   distribution from `conversations.conv_metadata.style_codename`.

## Files added by this change

| Path | Purpose |
|---|---|
| `docker-compose.yml` | New `grafana` service + Grafana data volume + nginx mount for `htpasswd` + Postgres init script mount |
| `nginx/default.conf` | New `stats.buju.ai` SSL server block + ACME entry |
| `nginx/htpasswd.example` | Placeholder; real htpasswd is gitignored |
| `postgres/init/01-grafana-ro.sh` | Creates the read-only `grafana_ro` role on first boot |
| `grafana/provisioning/datasources/postgres.yaml` | Datasource pointing at `postgres:5432` as `grafana_ro` |
| `grafana/provisioning/dashboards/buju.yaml` | Dashboard provider config |
| `grafana/dashboards/01-live-sessions.json` | Live sessions dashboard |
| `grafana/dashboards/02-recent-turns.json` | Recent turns dashboard |
| `grafana/dashboards/03-sessions-by-style.json` | Style + bandit dashboard |
| `STATS_DEPLOYMENT.md` | This file |
| `.env.template` (modified) | New `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_RO_PASSWORD` keys |
| `.gitignore` (modified) | Ignores `nginx/htpasswd` |

Backend repo also gets a one-line change in `JubuAdapter.start_conversation`
to stamp `style_codename` into `conv_metadata` so dashboard #3 has data
immediately. No DB migration required.

## First-time deployment on the server

Assumes you've already run the existing deploy workflow (`git pull` →
`docker compose build` → `docker compose up -d`) once and it works.

```bash
# 1. SSH into the server
gcloud compute ssh jubu-server --zone=us-west1-b
cd ~/jubu-deploy && git pull

# 2. Add the new env vars to .env (copy the new lines from .env.template)
echo 'GRAFANA_ADMIN_USER=admin'                   >> .env
echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 24)" >> .env
echo "GRAFANA_RO_PASSWORD=$(openssl rand -hex 24)"    >> .env

# 3. Generate the basic-auth file (apache2-utils for `htpasswd`)
sudo apt-get install -y apache2-utils
htpasswd -B -c nginx/htpasswd admin
# enter password when prompted

# 4. Point DNS for stats.buju.ai at this VM's PUBLIC_IP
#    (Cloudflare / Google Domains, A record, same as api.buju.ai etc.)

# 5. Issue the LetsEncrypt cert.  certbot uses the existing webroot loop.
docker compose up -d nginx       # ensure ACME route is reachable on :80
docker compose run --rm certbot certonly --webroot \
    -w /var/www/certbot \
    --email you@example.com \
    --agree-tos --no-eff-email \
    -d stats.buju.ai

# 6. Bootstrap the read-only Postgres role
#    (already-running deployments need this manual step; fresh volumes auto-run)
docker compose exec -T -e GRAFANA_RO_PASSWORD="$(grep GRAFANA_RO_PASSWORD .env | cut -d= -f2)" \
    postgres /docker-entrypoint-initdb.d/01-grafana-ro.sh

# 7. Bring up Grafana
docker compose up -d grafana
docker compose restart nginx

# 8. Verify
curl -sk https://stats.buju.ai/api/health   # 401 (basic-auth gate)
curl -sk -u admin:$BASIC_AUTH_PW https://stats.buju.ai/api/health
# {"database":"ok","version":"11.2.2",...}
```

Then open `https://stats.buju.ai` in a browser — basic-auth prompt, then
Grafana admin login (use `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`).
The three dashboards are under the "Buju" folder.

## Two-gate auth (Phase 0 reality check)

There are two passwords on the door right now:

1. **nginx basic-auth** — short circuit at the edge, single shared admin
   password. Stops casual scanning and bots.
2. **Grafana admin login** — gives you per-user accounts inside Grafana for
   when you eventually add other admins. Phase 3 collapses both into one
   parent-api SSO.

This is intentional: any one of the two breaking still leaves the dashboard
gated.

## COPPA posture today

- All transcripts and child profile data stay inside the existing Postgres,
  same VPC as the backend. Grafana queries them but never persists copies
  outside `/var/lib/grafana` (which holds dashboard layouts, not row data).
- Recent-turns panel **truncates `child_message` and `system_message` to 80
  characters** as a soft mitigation. Phase 3 replaces this with explicit
  click-to-reveal that writes to an `audit_log` table.
- Read-only DB role enforces "Grafana cannot mutate." Any attempt to
  `DELETE`/`UPDATE`/`INSERT` from Grafana fails with `permission denied`.
- Retention enforcement (90-day cron delete on `conversation_turns` and
  `telemetry_events`) lands in Phase 3 alongside SSO + audit log.
- No data leaves the VM. No third-party telemetry vendor receives child PII.

## Rollback

```bash
docker compose stop grafana
# Comment out the `grafana` service block in docker-compose.yml
# Remove the stats.buju.ai server block from nginx/default.conf
docker compose restart nginx
```

The `grafana_ro` Postgres role is harmless to leave; revoke with
`REVOKE ALL ON ALL TABLES IN SCHEMA public FROM grafana_ro;` if you want
zero footprint.

## What's next (Phase 1+)

- **Phase 1** — Persist `telemetry.emit()` events to a `telemetry_events`
  table; rebuild dashboards to show real-time `style.leak`, sentiment-by-
  style heatmaps, latency p99 from JSONL. ~2 days.
- **Phase 2** — Live "tail -f" conversation viewer with Postgres
  LISTEN/NOTIFY → SSE. ~3 days.
- **Phase 3** — SSO + audit log + default-redact + retention cron. ~3 days.

See `/Users/xhu/.claude/plans/please-take-a-look-shimmering-lemur.md` (or
the equivalent in your fork) for the full multi-phase plan.
