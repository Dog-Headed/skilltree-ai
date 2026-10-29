# Invited beta: email sign-in, isolation and bounded AI queue

## Identity and sessions

New accounts use a normalized lowercase email username and password. No email,
SMS, verification code or mailbox verification is involved. The login page offers
email/password registration with password confirmation (10 to 256 characters),
then signs the new user in. An administrator can also create an identity:

```sh
.venv/bin/python -m deploy.accounts --database data/auth.sqlite create person@example.com
```

The CLI prompts twice without echoing the password. It refuses to replace an
existing identity. Existing bcrypt htpasswd accounts are imported once using
`import-htpasswd /etc/skilltree/evaluators.htpasswd`, run by an administrator able
to read that private file. Import preserves each original canonical owner and
does not overwrite existing passwords. The public legacy-account checkbox has
been removed. Administrators can bind an email to an existing canonical owner
with `bind-email ACCOUNT EMAIL`; this preserves password hashes, sessions and
course ownership. Never infer ownership from a matching email supplied at signup.

Self-registration defaults to ten accounts (`SKILLTREE_REGISTRATION_LIMIT=10`);
administrator-created, imported and disabled identities do not consume these slots. The
capacity check is repeated atomically after hashing, so parallel registrations
cannot oversubscribe. Each IP gets at most ten registration attempts/hour.
Duplicate emails (case-insensitive) are refused and never replace an account.
Email is only a login name: there is no self-service email recovery; contact the
administrator for a forgotten password.

New passwords use salted PBKDF2-SHA256 with 600,000 iterations; bcrypt verification
exists only for legacy hashes. Raw session tokens are random 256-bit secrets;
only SHA256 verifiers are stored. HTTPS cookies use the `__Host-` prefix,
HttpOnly, Secure and SameSite=Lax. Remembered sessions last 30 days; session
cookies have a 12-hour server expiry. Logout revokes the current token.

All authenticated writes require a session-bound X-CSRF-Token. Login requires
JSON and a custom X-SkillTree-Login header. Writes reject cross-site Origin and
Sec-Fetch-Site values. A supplied X-Evaluation-User never authenticates the
production factory. No session credential is placed in browser localStorage.

These choices follow the [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
and [password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

GET /session returns canonical account, display login and csrf_token after
authentication. POST /auth/login accepts account, password, remember.
POST /auth/register additionally requires confirm_password, uses the same
JSON/origin protections and returns 201 plus the cookie. POST /auth/logout revokes it.
Eight failed attempts per identity or thirty per IP within fifteen minutes are
blocked temporarily. Password checks have two execution slots, separate from AI.

## Ownership

Existing project_owners rows remain authoritative. New creation atomically claims
the deterministic project identity with quota reservation. Foreign projects,
versions, sources and jobs return 404. Listing filters owner IDs before building
project views. Unassigned historical records remain hidden rather than guessed.

Browser selection, drafts and pending-job IDs are namespaced by canonical account.
Logout clears that account's browser drafts. Account switches notify other tabs;
history-cache restoration reloads the page. Production deletion remains disabled.

## Queue and protocol

Use **one Uvicorn worker**. An exclusive process lock prevents a second queue
owner. SQLite admission and claim transactions also enforce global capacity.

- Two slow AI workflows execute concurrently; up to ten workflows can be admitted
  in total, including the two executing.
- Each identity has at most one queued/running AI workflow.
- Begin, retry and potentially model-bearing resume commands return HTTP 202
  with a durable job ID. Poll GET /jobs/{id}; GET /jobs/active locates the current
  account's pending job. Results contain the original API status and public DTO.
- Project creation, uploads, rename and preparation-only commands do not consume
  AI execution slots. Fast writes to a project already queued/running are rejected
  promptly with a conflict; they do not wait behind its long model operation.
- Same account/path/request_id plus identical content returns the same job without
  a second debit or execution. Changed content with that identity is a conflict.
- Queue-full and account-busy rejections do not consume daily quota.
- Existing model budgets, frozen facts, project file locks and graph recovery
  continue to apply inside each job. A successful HTTP result alone is not proof
  of learning success; check page_state, feedback.guard and node state.

Jobs outlive the submitting HTTP connection. Persisted queued inputs can execute
after restart. Jobs found running after the prior process exits are marked
interrupted and **never automatically replayed**: read the saved course and use
the existing controlled recovery. Graceful shutdown stops admission and waits up
to 150 seconds for executors before process shutdown. Terminal job responses are
kept for three days; their submitted bodies are discarded after completion.

The app limits each account to 30 accepted writes/minute. Existing daily totals
stay **120 site-wide / 40 per account**: these count accepted HTTP write
operations, not model HTTP calls. They can still constrain a longer ten-person
trial. Raising them requires a separate cost/usage decision.

Nginx keeps coarse shared-IP protection: reads 60/s with burst 200, writes 60/min
with burst 40, connections 64. Login has its own 10/min with burst 10. Public
Uvicorn connection/task protection is 64; AI concurrency remains two.

## Local preview and validation

`python -m uvicorn deploy.preview:create_app --factory --host 127.0.0.1 --port 18231`
starts isolated real authentication/ownership/storage. Local-only identities
preview1@example.test through preview5@example.test use preview2026. They are not
created by the production factory. Data resides in work/beta-login-preview.
Preview model operations use the configured real provider; no auth mock is loaded.

Port 18230 remains the separate Claude design catalogue. Original local service
stays on 8765. Opt in with SKILLTREE_LOCAL_AUTH=1 only after backing up and
explicitly assigning existing local projects; its data/v3 directory stays in
place. Local 8765 and preview 18231 use different cookie names to avoid port
collisions in the browser. Production uses its original secure __Host- cookie.

Relevant checks: tests/test_beta_auth_queue.py, test_deployment_ownership.py,
test_deployment_gateway.py and the public API regression suite. The five-user
blocked-work test measures two executing / three waiting, isolation, duplicate
identity handling and responsiveness; its work is fake and does not establish
provider throughput. A separate real-provider check is required for capacity.

## Release and rollback

Back up all business/checkpoint SQLite databases with the SQLite backup API and
save the quota/ownership database, private runtime environment, htpasswd, Nginx
files and systemd unit in an owner-only server directory. Never publish these.
Check for executing projects and quiesce services for the final consistent backup.

Import legacy hashes before enabling cookie authentication. Install requirements,
fast-forward a clean checkout to the verified release, install the reviewed Nginx
and service files, validate nginx -t, restart the application and reload Nginx.
Keep 127.0.0.1 bindings and existing certificates. Verify unauthenticated redirect,
legacy/email login, old ownership, health and real job outcomes.

On failure stop new admission, stop services, and switch to the recorded prior
clean commit, restore the saved Nginx/unit/environment configuration, then restart.
Do not restore an old business database over new user work. New auth/queue tables
are additive and can be retained. Interrupted work requires read-first recovery.
