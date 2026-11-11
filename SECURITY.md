# Security

Please report vulnerabilities privately via GitHub's "Report a vulnerability" (Security
tab) rather than a public issue.

Notes for people running this:
- `.env` holds your Skylight password and the TV's developer password - keep it out of git.
- The server listens on your LAN without authentication and serves only the rendered
  dashboard images; don't expose port 8097 to the internet.
- CI never runs on your network: updates are pulled by `deploy/update.sh`. Don't attach a
  self-hosted runner from a home network to a public repository.
