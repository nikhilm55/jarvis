# Security

## Reporting

Report vulnerabilities privately to nikhil.malhotra@fiftyfivetech.io. Please don't open a public issue. You'll get a reply within 3 working days.

## Secrets

- Never commit credentials. `.env*`, keys and `secrets.toml` are gitignored. Pre-commit (`detect-secrets`, `detect-private-key`) and GitHub secret scanning with push protection act as backstops.
- The product stores user secrets in the OS keyring (FRS §7.3).
- AI agents are denied access to secrets and real user data by permission rules, the sandbox and hooks (`docs/ai/policy.md` §2).
