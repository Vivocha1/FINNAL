import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DB = Path(__file__).with_name("finnal_test.db")
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-keep-this-long-enough-for-ci"
os.environ["BOOTSTRAP_SECRET"] = "test-only-bootstrap-secret"
os.environ["EMPLOYER_MIN_COHORT"] = "2"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def create_employer(code: str, email: str):
    response = client.post("/api/bootstrap-employer", json={
        "bootstrap_secret": os.environ["BOOTSTRAP_SECRET"],
        "company_name": f"Company {code}",
        "company_code": code,
        "admin_name": "Admin User",
        "email": email,
        "password": "StrongTestPassword123!",
    })
    assert response.status_code == 200, response.text
    return response.json()


def create_employee(code: str, email: str):
    response = client.post("/api/register", json={
        "company_code": code,
        "name": "Test Employee",
        "email": email,
        "password": "StrongTestPassword123!",
    })
    assert response.status_code == 200, response.text
    return response.json()


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_budget_upsert_and_monthly_spending():
    create_employer("BUDGETCO", "admin-budget@example.com")
    employee = create_employee("BUDGETCO", "employee-budget@example.com")
    headers = auth(employee["access_token"])

    created = client.post("/api/budgets", headers=headers, json={
        "category": "Food", "month": "2026-11", "limit_paise": 100000
    })
    assert created.status_code == 200
    budget_id = created.json()["id"]

    # Saving the same user/category/month updates the existing budget, not duplicates it.
    updated = client.post("/api/budgets", headers=headers, json={
        "category": "Food", "month": "2026-11", "limit_paise": 120000
    })
    assert updated.status_code == 200
    assert updated.json()["id"] == budget_id

    tx = client.post("/api/transactions", headers=headers, json={
        "description": "Groceries", "amount_paise": 25000, "kind": "expense",
        "category": "Food", "occurred_on": "2026-11-07"
    })
    assert tx.status_code == 201

    budgets = client.get("/api/budgets?month=2026-11", headers=headers)
    assert budgets.status_code == 200
    food = budgets.json()["budgets"][0]
    assert food["spent_paise"] == 25000
    assert food["remaining_paise"] == 95000
    assert food["progress_pct"] == round(25000 / 120000 * 100, 1)

    deleted = client.delete(f"/api/budgets/{budget_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/budgets?month=2026-11", headers=headers).json()["budgets"] == []


def test_savings_goal_contributions_and_history():
    create_employer("SAVINGSCO", "admin-savings@example.com")
    employee = create_employee("SAVINGSCO", "employee-savings@example.com")
    headers = auth(employee["access_token"])

    goal = client.post("/api/savings-goals", headers=headers, json={
        "name": "Emergency fund", "target_paise": 200000,
        "due_date": "2027-06-30"
    })
    assert goal.status_code == 201
    goal_id = goal.json()["id"]
    assert goal.json()["progress_pct"] == 0

    contribution = client.post(f"/api/savings-goals/{goal_id}/contributions",
        headers=headers, json={"amount_paise": 50000, "note": "First deposit"})
    assert contribution.status_code == 201
    assert contribution.json()["goal"]["saved_paise"] == 50000
    assert contribution.json()["goal"]["progress_pct"] == 25
    assert contribution.json()["goal"]["remaining_paise"] == 150000

    history = client.get(f"/api/savings-goals/{goal_id}/contributions", headers=headers)
    assert history.status_code == 200
    assert history.json()["contributions"][0]["note"] == "First deposit"

    completed = client.post(f"/api/savings-goals/{goal_id}/contributions",
        headers=headers, json={"amount_paise": 200000})
    assert completed.status_code == 201
    assert completed.json()["goal"]["progress_pct"] == 100
    assert completed.json()["goal"]["is_completed"] is True
    assert completed.json()["goal"]["remaining_paise"] == 0


def test_money_routes_require_employee_role_and_are_tenant_scoped():
    employer = create_employer("TENANTONE", "admin-one@example.com")
    employee_one = create_employee("TENANTONE", "employee-one@example.com")
    create_employer("TENANTTWO", "admin-two@example.com")
    employee_two = create_employee("TENANTTWO", "employee-two@example.com")

    assert client.get("/api/budgets", headers=auth(employer["access_token"])).status_code == 403
    assert client.get("/api/employer/overview", headers=auth(employee_one["access_token"])).status_code == 403

    created = client.post("/api/savings-goals", headers=auth(employee_one["access_token"]),
        json={"name": "Private goal", "target_paise": 10000})
    assert created.status_code == 201
    goal_id = created.json()["id"]

    denied = client.post(f"/api/savings-goals/{goal_id}/contributions",
        headers=auth(employee_two["access_token"]), json={"amount_paise": 1000})
    assert denied.status_code == 404


def test_invalid_month_is_rejected():
    create_employer("DATECO", "admin-date@example.com")
    employee = create_employee("DATECO", "employee-date@example.com")
    response = client.get("/api/budgets?month=2026-13", headers=auth(employee["access_token"]))
    assert response.status_code == 422


def test_transaction_edit_and_delete_recalculate_budget():
    create_employer("TXCRUDCO", "admin-txcrud@example.com")
    employee = create_employee("TXCRUDCO", "employee-txcrud@example.com")
    headers = auth(employee["access_token"])

    client.post("/api/budgets", headers=headers, json={
        "category": "Food", "month": "2026-11", "limit_paise": 100000
    })
    tx = client.post("/api/transactions", headers=headers, json={
        "description": "Groceries", "amount_paise": 40000, "kind": "expense",
        "category": "Food", "occurred_on": "2026-11-07"
    })
    transaction_id = tx.json()["id"]

    update = client.put(f"/api/transactions/{transaction_id}", headers=headers, json={
        "description": "Updated groceries", "amount_paise": 25000, "kind": "expense",
        "category": "Food", "occurred_on": "2026-11-07"
    })
    assert update.status_code == 200
    budget = client.get("/api/budgets?month=2026-11", headers=headers).json()["budgets"][0]
    assert budget["spent_paise"] == 25000
    assert budget["remaining_paise"] == 75000

    deleted = client.delete(f"/api/transactions/{transaction_id}", headers=headers)
    assert deleted.status_code == 200
    budget = client.get("/api/budgets?month=2026-11", headers=headers).json()["budgets"][0]
    assert budget["spent_paise"] == 0


def test_goal_can_be_edited_and_contribution_corrected():
    create_employer("GOALEDITCO", "admin-goaledit@example.com")
    employee = create_employee("GOALEDITCO", "employee-goaledit@example.com")
    headers = auth(employee["access_token"])

    created = client.post("/api/savings-goals", headers=headers, json={
        "name": "Rainy day fund", "target_paise": 100000
    })
    goal_id = created.json()["id"]
    contribution = client.post(f"/api/savings-goals/{goal_id}/contributions",
        headers=headers, json={"amount_paise": 40000, "note": "Monthly contribution"})
    assert contribution.status_code == 201

    edited = client.put(f"/api/savings-goals/{goal_id}", headers=headers, json={
        "name": "Emergency fund", "target_paise": 80000, "due_date": "2027-06-30"
    })
    assert edited.status_code == 200
    assert edited.json()["name"] == "Emergency fund"
    assert edited.json()["progress_pct"] == 50
    assert edited.json()["due_date"] == "2027-06-30"

    history = client.get(f"/api/savings-goals/{goal_id}/contributions", headers=headers).json()
    contribution_id = history["contributions"][0]["id"]
    removed = client.delete(
        f"/api/savings-goals/{goal_id}/contributions/{contribution_id}", headers=headers
    )
    assert removed.status_code == 200
    assert removed.json()["goal"]["saved_paise"] == 0
    assert removed.json()["goal"]["progress_pct"] == 0

    assert client.delete(f"/api/savings-goals/{goal_id}", headers=headers).status_code == 200

def test_employer_dashboard_reports_only_cohort_tool_adoption():
    admin = create_employer("INSIGHTSCO", "admin-insights@example.com")
    employee_one = create_employee("INSIGHTSCO", "employee-insights-1@example.com")
    create_employee("INSIGHTSCO", "employee-insights-2@example.com")

    headers = auth(employee_one["access_token"])
    client.post("/api/budgets", headers=headers, json={
        "category": "Food", "month": "2026-11", "limit_paise": 50000
    })
    client.post("/api/savings-goals", headers=headers, json={
        "name": "Emergency reserve", "target_paise": 200000
    })

    response = client.get("/api/employer/overview", headers=auth(admin["access_token"]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["suppressed"] is False
    assert payload["employee_count"] == 2
    assert payload["employees_with_budgets"] == 1
    assert payload["budget_adoption_rate"] == 50.0
    assert payload["employees_with_savings_goals"] == 1
    assert payload["savings_goal_adoption_rate"] == 50.0
    assert "email" not in payload
    assert "individual_records" not in payload


def test_employer_insights_are_suppressed_below_minimum_cohort():
    admin = create_employer("SMALLCO", "admin-small@example.com")
    create_employee("SMALLCO", "employee-small@example.com")
    response = client.get("/api/employer/overview", headers=auth(admin["access_token"]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["suppressed"] is True
    assert "budget_adoption_rate" not in payload
    assert "savings_goal_adoption_rate" not in payload


def test_payroll_portfolio_consent_advisory_and_credit_review_workflow():
    admin = create_employer("FINANCEOS", "admin-financeos@example.com")
    admin_headers = auth(admin["access_token"])
    employee = create_employee("FINANCEOS", "employee-financeos@example.com")
    employee_headers = auth(employee["access_token"])

    advisor_created = client.post("/api/employer/advisors", headers=admin_headers, json={
        "name": "FINNAL Professional", "email": "advisor-financeos@example.com",
        "password": "StrongAdvisorPassword123!"
    })
    assert advisor_created.status_code == 201, advisor_created.text
    advisor_login = client.post("/api/login", json={
        "email": "advisor-financeos@example.com", "password": "StrongAdvisorPassword123!"
    })
    assert advisor_login.status_code == 200
    advisor_headers = auth(advisor_login.json()["access_token"])

    payroll = client.post("/api/payroll", headers=employee_headers, json={
        "month": "2026-11", "base_salary_paise": 3_000_000,
        "other_earnings_paise": 100_000, "overtime_paise": 50_000,
        "pf_deduction_paise": 180_000, "tax_deduction_paise": 50_000,
        "other_deductions_paise": 20_000, "deposited_paise": 2_900_000,
        "deposit_date": "2026-11-07", "notes": "Manual payslip entry"
    })
    assert payroll.status_code == 201, payroll.text
    assert payroll.json()["gross_salary_paise"] == 3_150_000
    assert payroll.json()["total_deductions_paise"] == 250_000
    assert payroll.json()["net_salary_paise"] == 2_900_000
    assert payroll.json()["verification"] == "employee_entered_unverified"

    invalid_payroll = client.post("/api/payroll", headers=employee_headers, json={
        "month": "2026-12", "base_salary_paise": 100_000,
        "pf_deduction_paise": 90_000, "tax_deduction_paise": 20_000
    })
    assert invalid_payroll.status_code == 422

    asset = client.post("/api/portfolio/assets", headers=employee_headers, json={
        "asset_type": "mutual_fund", "name": "Demo Index Fund",
        "institution": "Demo AMC", "invested_paise": 500_000,
        "current_value_paise": 525_000, "risk_band": "moderate",
        "as_of_date": "2026-11-07"
    })
    assert asset.status_code == 201, asset.text

    # Advisor must not see this employee until the employee explicitly consents.
    assert client.get("/api/advisor/employees", headers=advisor_headers).json()["employees"] == []
    denied = client.get(f"/api/advisor/employees/{employee['access_token']}", headers=advisor_headers)
    assert denied.status_code in (404, 422)

    profile = client.put("/api/financial-profile", headers=employee_headers, json={
        "monthly_essential_paise": 1_500_000, "emergency_fund_paise": 300_000,
        "dependents_count": 2, "risk_appetite": "moderate",
        "primary_goal": "Build emergency fund", "share_with_advisor": True
    })
    assert profile.status_code == 200
    assert profile.json()["share_with_advisor"] is True

    directory = client.get("/api/advisor/employees", headers=advisor_headers)
    assert directory.status_code == 200
    assert directory.json()["employees"][0]["id"] == client.get(
        "/api/me", headers=employee_headers).json()["id"]

    employee_id = directory.json()["employees"][0]["id"]
    detail = client.get(f"/api/advisor/employees/{employee_id}", headers=advisor_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["profile"]["emergency_fund_paise"] == 300_000
    assert detail.json()["payroll"][0]["deposited_paise"] == 2_900_000
    assert len(detail.json()["assets"]) == 1

    advisory = client.post(f"/api/advisor/employees/{employee_id}/advisories",
        headers=advisor_headers, json={
            "title": "Build your emergency reserve",
            "message": "Consider prioritising a liquid emergency reserve before increasing market exposure.",
            "topic": "planning"
        })
    assert advisory.status_code == 201, advisory.text
    messages = client.get("/api/advisories", headers=employee_headers)
    assert messages.status_code == 200
    message_id = messages.json()["messages"][0]["id"]
    assert client.post(f"/api/advisories/{message_id}/read", headers=employee_headers).status_code == 200

    loan = client.post("/api/loan-requests", headers=employee_headers, json={
        "requested_amount_paise": 500_000, "purpose": "Education",
        "notes": "Preliminary review requested"
    })
    assert loan.status_code == 201, loan.text
    queue = client.get("/api/advisor/loan-requests", headers=advisor_headers)
    assert queue.status_code == 200 and len(queue.json()["requests"]) == 1
    request_id = queue.json()["requests"][0]["id"]
    review = client.patch(f"/api/advisor/loan-requests/{request_id}", headers=advisor_headers,
        json={"status": "under_review", "indicative_amount_paise": 400_000,
              "advisor_note": "Subject to partner underwriting and verification"})
    assert review.status_code == 200
    own_requests = client.get("/api/loan-requests", headers=employee_headers).json()["requests"]
    assert own_requests[0]["status"] == "under_review"
    assert own_requests[0]["indicative_amount_paise"] == 400_000

    # Withdrawing consent removes advisor visibility.
    revoked = client.put("/api/financial-profile", headers=employee_headers, json={
        "monthly_essential_paise": 1_500_000, "emergency_fund_paise": 300_000,
        "dependents_count": 2, "risk_appetite": "moderate",
        "primary_goal": "Build emergency fund", "share_with_advisor": False
    })
    assert revoked.status_code == 200
    assert revoked.json()["share_with_advisor"] is False
    assert client.get(f"/api/advisor/employees/{employee_id}", headers=advisor_headers).status_code == 404


def test_advisor_cannot_read_other_company_employee_even_with_consent():
    admin_one = create_employer("ADVCOMPANY1", "admin-adv1@example.com")
    admin_two = create_employer("ADVCOMPANY2", "admin-adv2@example.com")
    employee_two = create_employee("ADVCOMPANY2", "employee-adv2@example.com")
    client.put("/api/financial-profile", headers=auth(employee_two["access_token"]), json={
        "monthly_essential_paise": 100000, "emergency_fund_paise": 100000,
        "dependents_count": 0, "risk_appetite": "conservative",
        "primary_goal": "Emergency fund", "share_with_advisor": True
    })
    client.post("/api/employer/advisors", headers=auth(admin_one["access_token"]), json={
        "name": "Advisor One", "email": "advisor-one@example.com",
        "password": "StrongAdvisorPassword123!"
    })
    advisor = client.post("/api/login", json={
        "email": "advisor-one@example.com", "password": "StrongAdvisorPassword123!"
    }).json()
    employee_id = client.get("/api/me", headers=auth(employee_two["access_token"])).json()["id"]
    response = client.get(f"/api/advisor/employees/{employee_id}", headers=auth(advisor["access_token"]))
    assert response.status_code == 404
