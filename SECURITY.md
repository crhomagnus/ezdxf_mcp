# Security Policy

## Supported release

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Do not disclose an exploitable vulnerability, token, account identifier,
private screenshot, or customer data in a public issue.

Contact the maintainer through the private contact methods listed on the
GitHub profile [@crhomagnus](https://github.com/crhomagnus). Include:

- affected version and component;
- impact and prerequisites;
- minimal reproduction steps;
- suggested mitigation, if known.

## Deployment expectations

- Keep the API and cursor bridge bound to loopback or a private authenticated
  network.
- Use independent random tokens of at least 32 characters and mode `0600`.
- Never commit tokens, private keys, screenshots, production hostnames, or job
  artifacts.
- Run the API and tunnel under dedicated unprivileged users.
- Review the reference systemd and SSH templates for the target environment.
- Preserve explicit confirmation for pointer movement.
- Add a separately reviewed adapter if clicks or keyboard actions are needed;
  the included bridge intentionally does not provide them.
