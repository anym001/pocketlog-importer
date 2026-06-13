# Security Policy

The importer handles bank export data and a PocketLog API key. Security
reports are taken seriously.

## Reporting a Vulnerability

Please **do not** report security vulnerabilities through public GitHub
issues, discussions, or pull requests.

Instead, use GitHub's **private vulnerability reporting**:

1. Open the [**Security**](https://github.com/anym001/pocketlog-importer/security)
   tab of this repository.
2. Click **"Report a vulnerability"** to open a private security advisory.

This keeps the report confidential between you and the maintainer until a fix
is available.

### What to include

- A description of the vulnerability and its impact
- Steps to reproduce (proof of concept, affected version, configuration)
- Any suggested mitigation, if known

### What to expect

- Acknowledgement of your report as soon as possible.
- An assessment and, where applicable, a fix released as a new version.
- Coordinated disclosure — please allow a reasonable window before any public
  disclosure.

### Please do not include real data

When sharing reproduction steps or logs, redact secrets (the PocketLog API
key, notification tokens) and use anonymised sample CSVs — never real bank
data.

## Supported Versions

Security fixes are provided for the **latest released version** only. Always
run the most recent image tag.
