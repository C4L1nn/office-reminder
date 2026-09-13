# Security Policy

## Supported versions

Security fixes are currently applied to the latest release line.

## Reporting a vulnerability

Please do not publish exploit details in a public issue.

Until a dedicated security contact is configured, use GitHub's private vulnerability
reporting feature for this repository if it is enabled. If private reporting is not
available, contact the maintainer privately through the GitHub profile linked to this
repository.

Please include:

- affected version or commit,
- reproduction steps,
- impact,
- suggested mitigation, if known.

## Sensitive data

Office Reminder is designed to keep runtime data local. Do not commit or attach:

- SQLite runtime databases,
- backups or exports,
- logs containing company information,
- credentials, tokens, private keys or `.env` files,
- customer/company-specific documents.

If a secret is ever committed, removing it from the latest branch is not sufficient.
Revoke/rotate the secret and rewrite repository history before making the repository public.
