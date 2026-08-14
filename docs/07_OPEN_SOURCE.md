# Open-source publishing checklist

The application code does not embed live credentials. `.env` and `local.settings.json` are gitignored
and have never been committed. That is necessary but not sufficient for a public repository.

Complete every remaining blocker before changing GitHub visibility to Public.

## Done

- The repository is licensed under Apache-2.0 (`LICENSE`, `NOTICE`, `pyproject.toml`).

## Blockers

1. **GitHub `production` environment variables are plaintext.** Secrets are stored correctly.
   Variables are not. GitHub documents that anyone with read access can see environment
   variable names and values. A public repository therefore publishes:
   - `DAILY_BRIEF_RECIPIENT` (a personal mailbox)
   - `ADMIN_MICROSOFT_HOME_ACCOUNT_ID`
   - Azure tenant / subscription / client IDs, Function app name, resource group, and the
     model endpoint
   Before going Public, delete `DAILY_BRIEF_RECIPIENT` from the environment (the live recipient
   already lives in PostgreSQL) and treat Azure identifiers as public fingerprints you accept,
   or move the ones you do not want listed into secrets.
2. **Decide the public identity.** The following strings name the current private deployment.
   They are not secrets, but they fingerprint the operator and the production Azure account:
   - `ada-zl5825/Agenda-Agent` in `.github/workflows/deploy-*.yml` and
     `scripts/bootstrap-azure.ps1`
   - `rg-agenda-agent-prod-uks` in bootstrap and database-maintenance script defaults
   - `authors = [{ name = "Theo" }]` in `pyproject.toml`
   Keep them if this GitHub account will remain the canonical home. Otherwise replace the script
   defaults with placeholders and require explicit `-GitHubRepository` / `-ResourceGroupName`.
3. **Keep the production GitHub `production` environment locked.** Secrets
   (`TOKEN_CACHE_ENCRYPTION_KEY`, Microsoft client secret, and the values bootstrap writes) must
   not become readable. Do not grant `secrets: write` to pull requests from forks. Required
   reviewers are optional for a solo owner; the environment currently allows only `main` and
   lets repository admins bypass.
4. **Leave the repository-name deploy guard in place, or replace it deliberately.**
   `github.repository == 'ada-zl5825/Agenda-Agent'` prevents a fork's `quality` workflow from
   deploying to this Azure subscription. That is intentional. A public fork must change the
   string to its own repository before it can deploy anywhere.

## Should do before Public

- Review `git log` and GitHub Issues / Discussions for pasted tokens, connection strings, or
  recruiter email content. None of `.env` / `local.settings.json` is in history today; still
  search commit messages and PR bodies.
- Confirm GitHub Actions does not log secret values. Current workflows pass Key Vault material
  through `secrets.*` and Azure OIDC variables, which is the correct pattern.
- Decide whether `infra/main.parameters.json` defaults (`uksouth`, `Europe/London`) should stay
  as examples. They are not credentials.
- Read Microsoft Graph, Azure, and model-provider terms. A public repo that talks to Graph and
  Azure OpenAI is fine; each operator still needs their own Entra app, mailbox consent, and
  model resource. Do not imply this is a Microsoft or LangGraph product.
- If you later accept third-party pull requests, add a short code of conduct and require
  contributors not to commit live mail, tokens, or production hostnames.

## Already acceptable to publish

- Application source, Alembic migrations, and tests. Fixtures use `example.test` / `example.com`.
- The reviewed public-company seed catalog (canonical employer names and public domains).
- `.env.example` with empty secrets.
- Privacy, workflow, and operations documents, after the resource-group examples are treated as
  placeholders (see [05_OPERATIONS.md](05_OPERATIONS.md)).
- Agent skills under `.agents/skills/`. They contain no credentials.

## Do not publish

- A real `.env`, Function `local.settings.json`, or exported MSAL cache.
- Production Application Insights dumps, Review screenshots that show recruiter mail, or Daily
  Brief HTML that still contains decrypted action links.
- Azure subscription IDs, tenant IDs, or client secrets in issues or README badges.
- The GitHub `production` environment secret store.

## After the repository is public

- Rotate Microsoft client secret, token-cache key, web-session key, ops token, and the
  link-encryption Key Vault secret if any of them ever appeared in a screenshot, chat, or CI log.
- Watch the first forks: they must not be able to obtain this repository's Azure OIDC token.
  The current immutable subject (owner ID + repository ID + `production` environment) is the
  control that makes that true.
- Keep `Mail.ReadWrite` out of the Entra app. A public clone that adds it would violate the
  project's privacy contract even if the code change looks small.
