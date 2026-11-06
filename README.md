# FINNAL — Financial Wellness Platform

FINNAL is an employee financial-wellness product with an employer administration dashboard. This repository currently contains the **backend API foundation** for the MVP.

## MVP scope currently implemented

- Employee and employer-admin authentication (JWT)
- Multi-tenant employer structure
- Employee-entered income/expense transactions and cash-flow summary
- Monthly budgets and savings goals/contributions
- Consent grant/revocation records
- Employer-level adoption aggregates with a configurable minimum cohort threshold
- Audit events for selected actions
- Health and database-readiness endpoints

**Not implemented:** lending/credit underwriting, investment custody or advice, payroll deduction execution, HRMS integrations, bank-account aggregation, KYC, or production-grade employee invitation workflows. These must be separate, reviewed integrations; this API does not initiate loans or move money.

## Architecture

- FastAPI + Pydantic
- SQLAlchemy 2.x
- PostgreSQL on Render (SQLite fallback for local smoke tests)
- Docker deployment
- OpenAPI docs at `/docs`

## Repository layout

```text
app/                 API, auth, models, schemas, database setup
 tests/               Smoke tests
Dockerfile            Container build
render.yaml           Render Blueprint (API + PostgreSQL)
requirements.txt      Python dependencies
.env.example          Local environment variable template
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs`. Local defaults use SQLite. For Docker, run `docker compose up --build`.

## Deploy using Render Blueprint

1. In Render, create a new Blueprint using this repository and the `render.yaml` file at the repository root.
2. Review the proposed web service and PostgreSQL resources, region, and plan before applying.
3. The Blueprint generates `JWT_SECRET` and `BOOTSTRAP_SECRET` and wires the API to the database's internal connection string.
4. Set `CORS_ORIGINS` to the exact HTTPS origin(s) of the deployed frontend. Do not use a wildcard for a credentialed production deployment.
5. After deployment, check `/health`, `/readyz`, and `/docs` on the service URL.

Do not commit secrets or real employee data. Keep the Render resources private and review current pricing in the Render dashboard before applying.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | API liveness |
| GET | `/readyz` | Database connectivity check |
| POST | `/v1/auth/bootstrap-employer` | Bootstrap an employer and initial admin (secret-protected) |
| POST | `/v1/auth/register-employee` | Demo employee registration using employer code |
| POST | `/v1/auth/login` | Login |
| GET | `/v1/me` | Current account |
| GET | `/v1/financial-overview` | Employee-entered cash-flow summary |
| GET/POST | `/v1/transactions` | List/create employee transactions |
| GET/PUT | `/v1/budgets` | List/upsert budgets |
| GET/POST | `/v1/savings-goals` | List/create goals |
| POST | `/v1/savings-goals/{id}/contributions` | Add to a goal |
| POST | `/v1/consents` | Record consent |
| POST | `/v1/consents/{id}/revoke` | Revoke consent |
| GET | `/v1/employer/aggregates` | Cohort-level employer indicators |

All amounts are integer **paise**. For example, ₹1,250.00 is `125000` paise.

## Important security and compliance boundaries

This is a **development/pilot foundation**, not a production-certified financial system. Before using real employee or financial data, add and independently test database migrations, email verification, password reset, MFA for employer admins, token revocation/rotation, rate limiting, secure invitation/HRMS-based onboarding, tenant-isolation defence in depth (including PostgreSQL row-level security), privacy controls, backups/restore drills, monitoring, and security testing. Review applicable Indian privacy, lending, KYC, payments, account-aggregator, and investment rules with qualified counsel and regulated partners. The employer endpoint returns aggregate indicators only, but cohort suppression by itself does not guarantee anonymity.

The current employer-code registration and bootstrap endpoints are intended only for controlled test use. Do not use them as-is for public onboarding.
