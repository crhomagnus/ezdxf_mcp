# Credential and Security Audit

Date: 2026-07-25
Release: 3.2.2

## Scope

The audit covered:

- every reachable public Git commit, branch, and tag;
- every file extracted from the public source archive, sdist, and wheel;
- GitHub release metadata, workflow output, issues, and secret-scanning alerts;
- exact-match comparison against high-confidence private credential values,
  performed in memory without recording the values;
- token files, process arguments, process environments, and service journals;
- API and cursor listeners, authentication failures, and SSH tunnel policy;
- Python dependencies and security-focused static analysis;
- archive path safety and deployment templates.

Private screenshots, customer data, credentials, and raw operational artifacts
were never copied into the audit workspace.

## Independent secret scans

Official release binaries were downloaded from their upstream GitHub projects
and verified against the SHA-256 digests published by GitHub.

| Scanner | Version | Git history | Extracted release files |
|---|---:|---:|---:|
| Gitleaks | 8.30.1 | 0 findings | 0 findings |
| TruffleHog, verified-only | 3.96.0 | 0 findings | 0 findings |
| GitHub Secret Scanning | hosted | 0 alerts | applies to repository |

GitHub Push Protection, Secret Scanning, Dependabot vulnerability alerts,
Dependabot security updates, and private vulnerability reporting are enabled.
The hosted account did not make non-provider pattern scanning or automatic
secret-validity checks available, so those two optional detectors remain
disabled. The earlier operational repository remains private and is not
reachable anonymously.

The exact-match audit compared high-confidence secret values from the private
credential store against public content. It found zero matches. The comparison
reported counts only and did not print or persist the values.

## Runtime credential checks

- API and cursor tokens are distinct.
- Token source and installed copies match their intended destinations.
- Token files are regular files, not symbolic links, with mode `0600`.
- No token was present in service command lines or process environments.
- No token was found in the relevant service journals.
- No token was found in project files, shell histories, session context files,
  or private project documentation outside the authorized credential store.
- API and cursor endpoints reject absent and incorrect credentials.
- Service ports bind to loopback and were closed or filtered from an external
  network path.
- Authenticated post-deployment checks reached the API through the restricted
  tunnel and completed a cursor-bridge dry run without moving the pointer.
- The deployed API and graphical bridge both report release 3.2.2.

## Code hardening

Release 3.2.2:

- opens secret files with no-follow semantics and checks type, ownership,
  permissions, link count, inode stability, size, encoding, and whitespace;
- refuses non-loopback API binds;
- accepts only literal loopback HTTP destinations for the internal cursor
  client;
- uses a fixed-destination HTTP client instead of a generic URL opener;
- requires an independently trusted SSH host-key fingerprint during
  installation;
- keeps the cursor bridge limited to pointer movement with confirmation,
  bounds checking, rate limiting, and idempotency.

Security-focused Ruff checks pass. `pip-audit` reported no known vulnerability
for the audited development, graphical-host, or VM third-party distributions
after the host and VM packaging tools were updated. The local project itself is
not a PyPI dependency and was reviewed through tests and static analysis.

Post-deployment `systemd-analyze security` exposure scores were 1.5 for the
graphical bridge, 1.4 for its SSH tunnel, and 1.3 for the VM API; systemd
classifies each score as `OK`.

## Residual security boundary

No finite audit can prove that a system has no unknown vulnerability. The
remaining material boundaries are:

- compromise of the operating-system user, root account, VM, GitHub account,
  or upstream package supply chain;
- a future undisclosed vulnerability in an image decoder, OCR engine, Python
  dependency, SSH implementation, or operating system;
- deliberate reconfiguration that disables loopback binding, file
  permissions, SSH restrictions, or repository protections;
- an authorized process reading a token from its own memory while it is using
  that token.

These are not observed credential leaks. They are the unavoidable trust
boundaries that must continue to be patched, monitored, and access-controlled.

## Conclusion

No direct or indirect credential disclosure was found in the public
repository, its reachable history, or its release artifacts. No currently
identified unauthenticated network path exposes the API or cursor credentials.
The hardening changes close the concrete weaknesses identified during review.
