# FINNAL — Employee financial wellness + employer insights

FINNAL is an early-stage MVP for MSME employee financial wellness. This public repository contains a same-origin web app, a FastAPI API, and Render configuration.

## Current MVP features

**Employee**
- Create an account using an employer code and sign in.
- Record income and expenses with category and date.
- View personal recorded income, expenses, net cash flow and transaction history.

**Employer**
- Create a company workspace and first employer-admin account through a bootstrap flow.
- Share the company code with employees during a controlled pilot.
- View cohort-level employee activity. Metrics are suppressed until the configured minimum cohort size is reached (default 10).

**Platform**
- SQLAlchemy-backed PostgreSQL on Render; SQLite for local development.
- PBKDF2-HMAC-SHA256 password hashing and short-lived signed JWT access tokens.
- Tenant-scoped user and transaction queries.
- Integer paise for monetary values (₹1,250.00 = 125000).
- Health, readiness and OpenAPI endpoints.
- Responsive PWA shell.

## Run locally

Requirements: Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. API docs: http://localhost:8000/docs.

Local development defaults use SQLite and a development-only bootstrap secret: local-bootstrap-only-change-this. This default is not suitable for deployment.

## First-time pilot setup

1. Open the app and select Employer setup.
2. For local development, enter the local bootstrap secret above. In Render, use the generated BOOTSTRAP_SECRET value from the service Environment page.
3. Create the employer workspace with a company code and admin account.
4. Share the company code with test employees. Employees sign up using that code.
5. Employees can sign in and record transactions. The employer view returns only aggregate activity and suppresses it until the minimum cohort is reached.

Never publish or share the bootstrap secret. Rotate it after initial provisioning; a dedicated provisioning process and disabling the bootstrap endpoint should be implemented before production use.

## Deploy on Render

The root render.yaml defines a Docker web service named finnal and managed PostgreSQL named finnal-postgres, both in Singapore. The service receives DATABASE_URL from the database and generated JWT_SECRET and BOOTSTRAP_SECRET values. Initial automatic deploys are disabled. Review the proposed service and database plans in Render before applying.

Review current pricing and resource sizing in the Render Dashboard before provisioning.

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Liveness |
| GET | /readyz | Database readiness |
| POST | /api/bootstrap-employer | Employer + admin setup |
| POST | /api/register | Employee sign-up using company code |
| POST | /api/login | Login |
| GET | /api/me | Current account |
| GET/POST | /api/transactions | Employee transaction history/create |
| GET | /api/overview | Employee cash-flow totals |
| GET | /api/employer/overview | Employer cohort indicators |

## Important limitations and security gates

This is a pilot MVP, not production-certified financial infrastructure. Do not enter real employee or financial data yet.

Not implemented: bank/account-aggregator connections, payroll or HRMS integrations, lending/underwriting, KYC, payment initiation, investment products, money movement, budgets, savings-goal workflows, email verification, password reset, MFA, refresh-token revocation, rate limiting, formal audit logging, database migrations, automated backup/restore drills, or PostgreSQL row-level security. The employer setup route is protected by a generated secret but is not yet a complete one-time provisioning lifecycle.

Before real pilot use, add Alembic migrations, employee invitation/roster verification, stronger account recovery and admin authentication, rate limiting, defence-in-depth tenant isolation with automated cross-tenant tests, privacy/retention/deletion controls, monitoring and security testing. Obtain qualified legal review for relevant Indian privacy, KYC, digital lending, payroll, account-aggregator, payment and investment rules, and use appropriately regulated partners.

Employer analytics suppress small cohorts, but a minimum-size threshold alone does not guarantee anonymity or prevent re-identification. Do not use employer insights for individual employee decisions.