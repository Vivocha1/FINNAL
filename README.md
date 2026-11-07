# FINNAL — Employee financial wellness + employer insights

FINNAL is an early-stage MVP for MSME employee financial wellness. This public repository contains a same-origin web app, a FastAPI API, and Render configuration.

## Current MVP features

**Employee**
- Create an account using an employer code and sign in.
- Record, edit and remove income/expense entries with category and date.
- View personal recorded income, expenses, net cash flow and transaction history.
- Review concise lessons on emergency funds, practical budgeting and the full cost of credit.
- Set monthly category budgets; spending is calculated from expense entries in that calendar month, with remaining/over-budget indicators.
- Create and edit savings goals with optional target dates, add dated contributions, review/correct contribution history and track completion progress.

**Employer / HR**
- Create a company workspace and first employer-admin account through a bootstrap flow.
- Share the company code with employees during a controlled pilot.
- Create FINNAL professional accounts for the company. Credentials must be shared securely with the authorised professional; the app does not send email invitations yet.
- View cohort-level employee activity, including adoption of budgeting and savings-goal tools. Metrics are suppressed until the configured minimum cohort size is reached (default 10); individual financial records are not shown.

**FINNAL professional**
- Sign in with a professional account created by the employer.
- View only employees who have actively enabled professional sharing consent.
- Review shared profile details, manually entered payroll, portfolio assets, category budgets and recent transactions.
- Send documented guidance to the employee app.
- Review preliminary credit requests and record a next step (under review, refer to lending partner, or not proceeding) with an optional indicative amount and note. This is not automated underwriting or a loan approval.

**Platform**
- SQLAlchemy-backed PostgreSQL on Render; SQLite for local development.
- PBKDF2-HMAC-SHA256 password hashing and short-lived signed JWT access tokens.
- Tenant-scoped user, transaction, budget, payroll, profile, portfolio, advisory and credit-request queries.
- Audit events for professional profile views, guidance and credit-review actions.
- New pilot tables are created on app start with SQLAlchemy create_all; formal Alembic migrations are still outstanding.
- PWA shell with app JavaScript split into a separately checked file.
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
| GET/POST/PUT/DELETE | /api/transactions | List, create, edit and remove employee transactions |
| GET | /api/overview | Employee cash-flow totals |
| GET/POST/DELETE | /api/budgets | Month-specific category budgets with calculated spending |
| GET/POST/PUT/DELETE | /api/savings-goals | Create, view, edit and remove savings goals |
| GET/POST/DELETE | /api/savings-goals/{goal_id}/contributions | List, record and correct contributions |
| GET | /api/employer/overview | Employer cohort indicators |
| POST | /api/employer/advisors | Create a company-scoped professional account |
| GET/PUT | /api/payroll | Employee manual payroll history and monthly upsert |
| DELETE | /api/payroll/{entry_id} | Remove a payroll record |
| GET/PUT | /api/financial-profile | Read/update employee financial profile and advisor-sharing consent |
| GET/POST/DELETE | /api/portfolio/assets | List, record and remove portfolio assets |
| GET | /api/advisories | Employee's professional guidance inbox |
| POST | /api/advisories/{message_id}/read | Mark guidance as read |
| POST/GET | /api/loan-requests | Submit and view employee preliminary credit requests |
| GET | /api/advisor/employees | Consent-sharing employees for the professional |
| GET | /api/advisor/employees/{employee_id} | Read employee's consented financial details |
| POST | /api/advisor/employees/{employee_id}/advisories | Send professional guidance |
| GET | /api/advisor/loan-requests | List consented preliminary credit requests |
| PATCH | /api/advisor/loan-requests/{request_id} | Save preliminary credit review status and note |

## Important limitations and security gates

This is a pilot MVP, not production-certified financial infrastructure. Do not enter real employee or financial data yet.

Not implemented: bank/account-aggregator connections, payroll or HRMS integrations, lending/underwriting, KYC, payment initiation, investment products, money movement, email verification, password reset, MFA, refresh-token revocation, rate limiting, formal audit logging, database migrations, automated backup/restore drills, or PostgreSQL row-level security. The employer setup route is protected by a generated secret but is not yet a complete one-time provisioning lifecycle.

This expanded code is still a controlled prototype. Payroll values are manually entered and marked unverified. Portfolio values are self-reported. Professional visibility is limited by explicit employee consent and recorded in the audit_events table, but this is not a full consent-management or compliance system. Indicative loan amounts and statuses are workflow notes, not credit approvals or commitments. Do not enter real customer or employee financial data until security and legal reviews are complete.

Before a real pilot, add Alembic migrations (the existing create_all will create the new tables but is not a migration strategy), invitation/roster verification, stronger account recovery and admin authentication, rate limiting, defence-in-depth tenant isolation with automated cross-tenant tests, robust consent expiry/revocation and data deletion, audit log protection, monitoring, backups/restore testing and security review. Obtain qualified legal review for applicable Indian privacy, investment-advisory, mutual-fund distribution, digital-lending, KYC, payroll, account-aggregator and payment rules. Use appropriately regulated partners for regulated activities.

Employer analytics suppress small cohorts, but a minimum-size threshold alone does not guarantee anonymity or prevent re-identification. Do not use employer insights for individual employee decisions.

## Tests

Install development dependencies and run the API tests:

```bash
pip install -r requirements-dev.txt
pytest -q
```

GitHub Actions runs the API tests and checks the browser JavaScript syntax on pushes to `main` and pull requests.
