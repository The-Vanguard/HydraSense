# Security Policy

## Supported Versions

HydraSense is currently in active development as a research prototype submitted for
Smart India Hackathon 2026. Security updates are applied to the latest development
build only.

| Version | Supported |
| ------- | --------- |
| Latest (main) | Yes |
| Older branches | No |

## Scope

This policy covers the following components of HydraSense:

- **Backend API** ” FastAPI application (`backend/`) including all routers, the risk engine, and the alert pipeline
- **Frontend Dashboard** ” React + Leaflet application (`frontend/`)
- **IoT Simulator** ” MQTT-based sensor ingestion layer (`iot/`)
- **ML Pipeline** ” Feature engineering, model training, and inference scripts (`ml/`, `data/multiregion/scripts/`)

The following are out of scope:

- Third-party upstream data sources (IMD, Open-Meteo, ERA5-Land, OpenTopography)
- The ntfy.sh push notification service
- GitHub Actions CI infrastructure

## Reporting a Vulnerability

If you discover a security vulnerability in HydraSense, please report it responsibly
by emailing the project maintainer directly:

**Contact:** mohanrajguhan@gmail.com  
**Subject line:** `[HydraSense Security] <brief description>`

Please include the following in your report:

- A clear description of the vulnerability and its potential impact
- The component affected (backend, frontend, ML pipeline, IoT layer)
- Steps to reproduce the issue
- Any proof-of-concept code or screenshots, if applicable

### What to expect

- **Acknowledgement:** You will receive a response within 48 hours confirming receipt
  of your report.
- **Assessment:** The maintainer will assess severity and reproducibility within 5
  business days and provide an initial status update.
- **Resolution:** For confirmed vulnerabilities, a fix will be developed and deployed
  as soon as possible. You will be notified when the fix is released.
- **Disclosure:** We follow a coordinated disclosure model. Please allow a reasonable
  remediation window before public disclosure. We will coordinate timing with you.

### What not to report

- Vulnerabilities in third-party dependencies that are already publicly known and
  tracked upstream (please open a regular issue or dependency update PR instead)
- Issues specific to test or development environment configurations
- Rate-limiting or denial-of-service scenarios against the local development server

## Known Security Considerations

### API Authentication

The current prototype does not implement API authentication. The backend is intended
to run in a controlled local or internal network environment. Do not expose the FastAPI
server directly to the public internet without adding authentication middleware.

### GitHub Tokens

GitHub Personal Access Tokens used for deployment are stored in the git remote URL
during development. Tokens should be rotated regularly and never committed into source
files. The `.gitignore` excludes `.env` files; use environment variables for any
credentials in production.

### Data Handling

HydraSense processes geospatial risk data for early warning purposes. Ensure that any
production deployment follows applicable data protection regulations. No personally
identifiable information (PII) is collected or stored by the system in its current form.

## Attribution

We are grateful to security researchers who report vulnerabilities responsibly. Confirmed
valid reports will be acknowledged in the project release notes.
