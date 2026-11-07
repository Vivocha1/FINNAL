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
