# Open-source publishing checklist

The application code does not embed live credentials. `.env` and `local.settings.json` are gitignored
and have never been committed.

## Done before Public

- Licensed under Apache-2.0 (`LICENSE`, `NOTICE`, `pyproject.toml`).
- `DAILY_BRIEF_RECIPIENT` is not a GitHub environment variable. The live recipient lives in
  PostgreSQL.
- `ADMIN_MICROSOFT_HOME_ACCOUNT_ID` stays a `production` environment variable. It is a public
  fingerprint, not a credential.
- `main` is protected by a repository ruleset: pull request required, `checks` must pass, no force
  push, no branch deletion. Repository admins may bypass only when merging a pull request.
- The `production` environment deploys only from `main`. Repository admins cannot bypass that
  branch policy.
- Dependabot alerts and Dependabot security updates are enabled.
- Secret scanning, private vulnerability reporting, and push rulesets that block `.env` are
  unavailable on this private user-owned repository. They become available after the repository
  is Public (secret scanning / private reporting) or if the repository is moved under an
  organization (push rulesets).
- Actions default `GITHUB_TOKEN` permissions are read-only. Deploy workflows still require
  `github.repository == 'ada-zl5825/Agenda-Agent'` and a successful `quality` run on this
  repository, so a fork cannot obtain this subscription's Azure OIDC token.
- Community files are in place: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and
  pull-request templates, and Dependabot.

## Accepted public fingerprints

These are not credentials. They identify this repository's production Azure account and stay as
GitHub `production` environment variables because deploy workflows and `azure/login` read them:

- Azure tenant / subscription / client IDs
- Function app name, resource group, and model endpoint
- Microsoft application and connection IDs
- `ADMIN_MICROSOFT_HOME_ACCOUNT_ID`
- feature flags such as `MAIL_SYNC_ENABLED`

Keep the deploy-guard string `ada-zl5825/Agenda-Agent`. A public fork must change it to its own
repository before it can deploy anywhere.

## Do not publish

- A real `.env`, Function `local.settings.json`, or exported MSAL cache.
- Production Application Insights dumps, Review screenshots that show recruiter mail, or Daily
  Brief HTML that still contains decrypted action links.
- The GitHub `production` environment secret store.
- Personal mailbox addresses in environment variables, issues, or README badges.

## After the repository is public

- Confirm GitHub Security Advisories show **Report a vulnerability**.
- Watch the first forks: they must not be able to obtain this repository's Azure OIDC token.
  The current immutable subject (owner ID + repository ID + `production` environment) is the
  control that makes that true.
- Rotate Microsoft client secret, token-cache key, web-session key, ops token, and the
  link-encryption Key Vault secret if any of them ever appeared in a screenshot, chat, or CI log.
- Keep `Mail.ReadWrite` out of the Entra app. A public clone that adds it would violate the
  project's privacy contract even if the code change looks small.
