# SkillTree V3 production deployment

The original V3 graphs and business rules are unchanged. `deploy.asgi` adds
evaluation-only controls outside the application: persistent daily quotas,
two simultaneous writes, a local health route, and blocked destructive,
legacy, and documentation routes. Authenticated accounts have separate project
lists and authorization on every project, source, quiz and write route. Creation
request replay cannot take ownership of another account's project. Ownership
persists alongside quota records; old unassigned projects stay hidden until the
owner confirms their account. This is Basic-auth account isolation, without
self-service registration, password recovery, or a full account management UI.

## Runtime

Ubuntu 24.04 / Python 3.12, existing `.venv`, one Uvicorn worker per service.
`skilltree` retains the existing data/v3 records on 127.0.0.1:8765;
`skilltree-evaluation` uses a separate data/evaluation-v3 store on 127.0.0.1:8767.
Nginx only proxies the isolated evaluation store and initially listens on
127.0.0.1:8080. Public publishing
requires the owner's explicit approval and the cloud firewall allowing 80/443.
Never open 8765 or 8767. Keep `.env` mode 600, data/backups private, and credentials
outside Git. Provision evaluation password hashes with `create_evaluators.py`;
the script never prints passwords or replaces existing credentials.

Limits: 120 write requests/day globally, 40/account/day, reset at UTC+8
midnight; 6 writes/minute/IP with burst 3; 256 KiB request bodies; 2 concurrent
writes. All POST/PATCH attempts consume quota, including invalid submissions.
These are request limits, not token or currency budgets: one accepted action
can invoke several bounded model tasks. Existing V3 per-operation model budgets
still apply. Set provider-side spending limits separately if supported.

Read requests do not invoke the model. `/healthz` validates business storage
availability, not teaching quality or provider availability. The two-minute
timer logs failed health checks. Systemd restarts crashed processes; it does
not repeatedly restart a healthy process after provider failures.

Nginx has a 600-second response timeout for multi-task model operations. The
deployment adapter allows 150 seconds for a model response (the provider documents
a 120-second response window); the original local adapter and business budgets
remain unchanged. `SKILLTREE_THINKING_MODE=auto|true|false` controls the provider's
documented thinking option. The evaluation deployment uses `false`: the same
frozen quiz timed out at 150 seconds in default deep-thinking mode, while the
non-thinking call plus existing bounded output repair produced a valid quiz.
Strict schema, scoring, progression guards and durable recovery remain intact.
The deployment provider retains LangChain/Pydantic's strict parsing and reports
concise field paths or JSON syntax locations to the existing single-repair
budget. It does not copy an entire failed completion/frozen snapshot into the
repair prompt, guess missing fields, rewrite identities, or add hidden retries.
Journald is bounded to 150 MiB/14 days; Nginx logs rotate daily/10 MiB, 14 copies.
Access logs exclude query strings, credentials, and request/response bodies.

The authenticated gateway returns `/session`; the UI displays the current
account and separates browser drafts/selections by account. Standalone local
V3 returns an anonymous session and retains its previous local storage keys.
After an offline backup, confirmed historical ownership can be assigned with
`python -m deploy.assign_projects --root data/evaluation-v3 --registry data/evaluation-quota.sqlite PROJECT_ID=ACCOUNT`.
Assignments never replace an existing owner. Always back up the ownership/quota
database together with business and checkpoint stores.

## Backup and rollback

Stop both services/all writers before `python deploy/backup.py REPO NEW_BACKUP_DIRECTORY`.
It backs up all SQLite stores with SQLite's backup API and integrity checks,
copies `.env` privately, and archives the current committed code. A backup
contains a manifest and must remain outside the repository. The initial
deployment also saves system service and Nginx configuration.

To roll back, stop the service, **first back up current data again**, and restore
the archived prior code into a new release directory; retain the old release
and point the service working directory/command at the recovered release.
Copy `.env` privately. Initially keep current databases if compatible. If an
offline migration requires restoring a paired snapshot, inspect all learning
records created since that backup and obtain owner approval before replacing
production data. Never reset Git over local changes or delete production data.

## Public TLS without a domain

Let's Encrypt/Certbot supports short-lived IP certificates. Install Certbot
5.4 or later into `/opt/skilltree-certbot`, then, **after approval**, run
`bash deploy/publish-ip.sh --approved-public-access`. Port 80 initially serves
only ACME validation. Once the certificate succeeds, HTTP redirects to HTTPS
and authenticated HTTPS proxies to the loopback application. The timer checks
renewal twice daily and reloads Nginx after renewal. Do not bypass a browser
certificate warning. If issuance fails, check cloud firewall access to port 80.

With the owner's domain, prefer `skilltree.goutouren.work`: create an A record
`skilltree -> 47.82.118.171`, wait until public DNS resolves correctly, then run
`bash deploy/publish-domain.sh --approved-public-access`. Existing root-domain
and other service records must remain untouched. The domain script obtains a
regular domain certificate and sets up twice-daily renewal checks.

## GitHub deployment automation

`github-actions.yml.example` is a reviewable template, deliberately inactive.
After approving the production environment and a dedicated, restricted SSH
credential, place it at `.github/workflows/deploy.yml`. Store only that dedicated
credential in the environment secret `SKILLTREE_DEPLOY_KEY` and verified server
host keys in `SKILLTREE_KNOWN_HOSTS`; never upload the current personal SSH key.
Require environment approval for production. CI runs tests, then deploys the
tested full commit hash. The deployment refuses dirty worktrees, non-fast-forward
updates, dependency changes, and infrastructure changes. It stops writers,
backs up data, verifies `.env` unchanged, and checks health. Infrastructure and
dependency updates require a reviewed manual deployment. A failed rollout does
not automatically overwrite databases or discard learning records.
