import os, hashlib, hmac, secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from jose import jwt, JWTError
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, ForeignKey, func, text, UniqueConstraint, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session

APP_SECRET = os.getenv("JWT_SECRET", "local-development-only-change-this-secret")
BOOTSTRAP_SECRET = os.getenv("BOOTSTRAP_SECRET", "local-bootstrap-only-change-this")
TOKEN_TTL_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", "60"))
MIN_COHORT = int(os.getenv("EMPLOYER_MIN_COHORT", "10"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./finnal.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def utcnow_naive():
    # Store UTC timestamps as naive values for compatibility with existing DateTime columns.
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    code = Column(String(48), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="employee", nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    description = Column(String(160), nullable=False)
    amount_paise = Column(Integer, nullable=False)
    kind = Column(String(12), nullable=False)
    category = Column(String(48), default="Other", nullable=False)
    occurred_on = Column(Date, default=date.today, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("company_id", "user_id", "category", "month",
        name="uq_budget_user_category_month"),)
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    category = Column(String(48), nullable=False)
    month = Column(Date, nullable=False)
    limit_paise = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

class SavingsGoal(Base):
    __tablename__ = "savings_goals"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    name = Column(String(120), nullable=False)
    target_paise = Column(Integer, nullable=False)
    saved_paise = Column(Integer, default=0, nullable=False)
    due_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

class GoalContribution(Base):
    __tablename__ = "goal_contributions"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    goal_id = Column(Integer, ForeignKey("savings_goals.id"), index=True, nullable=False)
    amount_paise = Column(Integer, nullable=False)
    note = Column(String(160), default="", nullable=False)
    contributed_on = Column(Date, default=date.today, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)


class PayrollEntry(Base):
    __tablename__ = "payroll_entries"
    __table_args__ = (UniqueConstraint("company_id", "user_id", "month",
        name="uq_payroll_user_month"),)
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    month = Column(Date, nullable=False)
    base_salary_paise = Column(Integer, nullable=False)
    other_earnings_paise = Column(Integer, default=0, nullable=False)
    overtime_paise = Column(Integer, default=0, nullable=False)
    pf_deduction_paise = Column(Integer, default=0, nullable=False)
    tax_deduction_paise = Column(Integer, default=0, nullable=False)
    other_deductions_paise = Column(Integer, default=0, nullable=False)
    deposited_paise = Column(Integer, default=0, nullable=False)
    deposit_date = Column(Date, nullable=True)
    notes = Column(String(240), default="", nullable=False)
    source = Column(String(24), default="employee_manual", nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

class FinancialProfile(Base):
    __tablename__ = "financial_profiles"
    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_financial_profile_user"),)
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    monthly_essential_paise = Column(Integer, default=0, nullable=False)
    emergency_fund_paise = Column(Integer, default=0, nullable=False)
    dependents_count = Column(Integer, default=0, nullable=False)
    risk_appetite = Column(String(24), default="not_set", nullable=False)
    primary_goal = Column(String(160), default="", nullable=False)
    share_with_advisor = Column(Boolean, default=False, nullable=False)
    consent_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

class PortfolioAsset(Base):
    __tablename__ = "portfolio_assets"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    asset_type = Column(String(32), nullable=False)
    name = Column(String(120), nullable=False)
    institution = Column(String(120), default="", nullable=False)
    invested_paise = Column(Integer, default=0, nullable=False)
    current_value_paise = Column(Integer, nullable=False)
    risk_band = Column(String(24), default="not_set", nullable=False)
    as_of_date = Column(Date, default=date.today, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

class AdvisoryMessage(Base):
    __tablename__ = "advisory_messages"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    employee_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    advisor_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String(120), nullable=False)
    message = Column(String(2000), nullable=False)
    topic = Column(String(32), default="planning", nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    read_at = Column(DateTime, nullable=True)

class LoanRequest(Base):
    __tablename__ = "loan_requests"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    employee_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    requested_amount_paise = Column(Integer, nullable=False)
    purpose = Column(String(160), nullable=False)
    notes = Column(String(500), default="", nullable=False)
    status = Column(String(32), default="received", nullable=False)
    indicative_amount_paise = Column(Integer, nullable=True)
    advisor_note = Column(String(1000), default="", nullable=False)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    subject_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    action = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)


Base.metadata.create_all(bind=engine)
app = FastAPI(title="FINNAL API", version="0.1.0",
    description="Employee financial wellness and employer cohort insights prototype")

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return salt.hex() + "$" + value.hex()

def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        value = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310000)
        return hmac.compare_digest(value.hex(), hash_hex)
    except (ValueError, TypeError):
        return False

def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "company": user.company_id,
        "role": user.role, "iat": now, "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES)},
        APP_SECRET, algorithm="HS256")

def current_user(authorization: Optional[str] = Header(default=None),
                 db: Session = Depends(db_session)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue")
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], APP_SECRET, algorithms=["HS256"])
        user_id, company_id = int(payload["sub"]), int(payload["company"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired session")
    user = db.query(User).filter(User.id == user_id, User.company_id == company_id).first()
    if not user:
        raise HTTPException(401, "Account not found")
    return user

def employee(user: User = Depends(current_user)) -> User:
    if user.role != "employee":
        raise HTTPException(403, "Employee account required")
    return user

def employer(user: User = Depends(current_user)) -> User:
    if user.role != "employer_admin":
        raise HTTPException(403, "Employer administrator account required")
    return user

class BootstrapIn(BaseModel):
    bootstrap_secret: str
    company_name: str = Field(min_length=2, max_length=160)
    company_code: str = Field(min_length=4, max_length=48)
    admin_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

class RegisterIn(BaseModel):
    company_code: str
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TransactionIn(BaseModel):
    description: str = Field(min_length=1, max_length=160)
    amount_paise: int = Field(gt=0, le=100_000_000)
    kind: str
    category: str = Field(default="Other", max_length=48)
    occurred_on: date = Field(default_factory=date.today)

class BudgetIn(BaseModel):
    category: str = Field(min_length=1, max_length=48)
    month: str = Field(min_length=7, max_length=7)
    limit_paise: int = Field(gt=0, le=1_000_000_000)

class SavingsGoalIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    target_paise: int = Field(gt=0, le=10_000_000_000)
    due_date: Optional[date] = None

class SavingsGoalUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    target_paise: Optional[int] = Field(default=None, gt=0, le=10_000_000_000)
    due_date: Optional[date] = None

class GoalContributionIn(BaseModel):
    amount_paise: int = Field(gt=0, le=1_000_000_000)
    note: str = Field(default="", max_length=160)
    contributed_on: date = Field(default_factory=date.today)


class PayrollIn(BaseModel):
    month: str = Field(min_length=7, max_length=7)
    base_salary_paise: int = Field(ge=0, le=1_000_000_000)
    other_earnings_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    overtime_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    pf_deduction_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    tax_deduction_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    other_deductions_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    deposited_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    deposit_date: Optional[date] = None
    notes: str = Field(default="", max_length=240)

class FinancialProfileIn(BaseModel):
    monthly_essential_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    emergency_fund_paise: int = Field(default=0, ge=0, le=1_000_000_000)
    dependents_count: int = Field(default=0, ge=0, le=30)
    risk_appetite: str = Field(default="not_set", max_length=24)
    primary_goal: str = Field(default="", max_length=160)
    share_with_advisor: bool = False

class PortfolioAssetIn(BaseModel):
    asset_type: str = Field(max_length=32)
    name: str = Field(min_length=2, max_length=120)
    institution: str = Field(default="", max_length=120)
    invested_paise: int = Field(default=0, ge=0, le=10_000_000_000)
    current_value_paise: int = Field(ge=0, le=10_000_000_000)
    risk_band: str = Field(default="not_set", max_length=24)
    as_of_date: date = Field(default_factory=date.today)

class AdvisorCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

class AdvisoryIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=5, max_length=2000)
    topic: str = Field(default="planning", max_length=32)

class LoanRequestIn(BaseModel):
    requested_amount_paise: int = Field(gt=0, le=50_000_000)
    purpose: str = Field(min_length=3, max_length=160)
    notes: str = Field(default="", max_length=500)

class LoanReviewIn(BaseModel):
    status: str = Field(min_length=5, max_length=32)
    indicative_amount_paise: Optional[int] = Field(default=None, ge=0, le=50_000_000)
    advisor_note: str = Field(default="", max_length=1000)


@app.get("/health")
def health():
    return {"status": "ok", "service": "finnal"}

@app.get("/readyz")
def readyz(db: Session = Depends(db_session)):
    try:
        db.execute(text("SELECT 1")).scalar_one()
        return {"status": "ready", "database": "reachable"}
    except Exception:
        raise HTTPException(503, "Database unavailable")

@app.post("/api/bootstrap-employer")
def bootstrap_employer(body: BootstrapIn, db: Session = Depends(db_session)):
    if not hmac.compare_digest(body.bootstrap_secret, BOOTSTRAP_SECRET):
        raise HTTPException(403, "Invalid bootstrap secret")
    if db.query(Company).filter(Company.code == body.company_code).first():
        raise HTTPException(409, "Company code already exists")
    if db.query(User).filter(func.lower(User.email) == body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    company = Company(name=body.company_name, code=body.company_code)
    db.add(company); db.flush()
    user = User(company_id=company.id, name=body.admin_name, email=body.email.lower(),
        password_hash=password_hash(body.password), role="employer_admin")
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": issue_token(user), "role": user.role, "company": company.name}

@app.post("/api/register")
def register(body: RegisterIn, db: Session = Depends(db_session)):
    company = db.query(Company).filter(Company.code == body.company_code).first()
    if not company:
        raise HTTPException(404, "Company code not found")
    if db.query(User).filter(func.lower(User.email) == body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    user = User(company_id=company.id, name=body.name, email=body.email.lower(),
        password_hash=password_hash(body.password), role="employee")
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": issue_token(user), "role": user.role, "name": user.name}

@app.post("/api/login")
def login(body: LoginIn, db: Session = Depends(db_session)):
    user = db.query(User).filter(func.lower(User.email) == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": issue_token(user), "role": user.role, "name": user.name}

@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(db_session)):
    company = db.query(Company).filter(Company.id == user.company_id).first()
    return {"id": user.id, "name": user.name, "email": user.email,
        "role": user.role, "company": company.name if company else ""}

@app.get("/api/transactions")
def list_transactions(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(Transaction).filter(Transaction.company_id == user.company_id,
        Transaction.user_id == user.id).order_by(Transaction.occurred_on.desc(), Transaction.id.desc()).limit(100).all()
    return [{"id": r.id, "description": r.description, "amount_paise": r.amount_paise,
        "kind": r.kind, "category": r.category, "occurred_on": r.occurred_on.isoformat()} for r in rows]

@app.post("/api/transactions", status_code=201)
def add_transaction(body: TransactionIn, user: User = Depends(employee),
                    db: Session = Depends(db_session)):
    if body.kind not in ("income", "expense"):
        raise HTTPException(422, "kind must be income or expense")
    row = Transaction(company_id=user.company_id, user_id=user.id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "message": "Transaction saved"}

@app.put("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: int, body: TransactionIn,
                       user: User = Depends(employee), db: Session = Depends(db_session)):
    if body.kind not in ("income", "expense"):
        raise HTTPException(422, "kind must be income or expense")
    row = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.company_id == user.company_id,
        Transaction.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(404, "Transaction not found")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.commit()
    return {"id": row.id, "message": "Transaction updated"}

@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, user: User = Depends(employee),
                       db: Session = Depends(db_session)):
    row = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.company_id == user.company_id,
        Transaction.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(404, "Transaction not found")
    db.delete(row)
    db.commit()
    return {"message": "Transaction removed"}

@app.get("/api/overview")
def overview(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(Transaction).filter(Transaction.company_id == user.company_id,
        Transaction.user_id == user.id).all()
    income = sum(r.amount_paise for r in rows if r.kind == "income")
    expense = sum(r.amount_paise for r in rows if r.kind == "expense")
    return {"income_paise": income, "expense_paise": expense,
        "net_paise": income - expense, "transaction_count": len(rows)}

def parse_month(value: Optional[str] = None) -> date:
    raw = value or date.today().strftime("%Y-%m")
    try:
        if len(raw) != 7:
            raise ValueError()
        return datetime.strptime(raw, "%Y-%m").date().replace(day=1)
    except ValueError:
        raise HTTPException(422, "month must use YYYY-MM format")

def month_after(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)

def goal_result(goal: SavingsGoal) -> dict:
    progress = min(100.0, round(goal.saved_paise / goal.target_paise * 100, 1))
    return {
        "id": goal.id, "name": goal.name, "target_paise": goal.target_paise,
        "saved_paise": goal.saved_paise,
        "remaining_paise": max(0, goal.target_paise - goal.saved_paise),
        "progress_pct": progress, "is_completed": goal.saved_paise >= goal.target_paise,
        "due_date": goal.due_date.isoformat() if goal.due_date else None,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
    }

@app.get("/api/budgets")
def list_budgets(month: Optional[str] = None, user: User = Depends(employee),
                 db: Session = Depends(db_session)):
    start = parse_month(month)
    end = month_after(start)
    budgets = db.query(Budget).filter(
        Budget.company_id == user.company_id, Budget.user_id == user.id,
        Budget.month == start
    ).order_by(Budget.category.asc()).all()
    spent_rows = db.query(Transaction.category, func.coalesce(func.sum(Transaction.amount_paise), 0)).filter(
        Transaction.company_id == user.company_id, Transaction.user_id == user.id,
        Transaction.kind == "expense", Transaction.occurred_on >= start,
        Transaction.occurred_on < end
    ).group_by(Transaction.category).all()
    spent = {category: int(amount) for category, amount in spent_rows}
    result = []
    for budget in budgets:
        amount_spent = spent.get(budget.category, 0)
        result.append({
            "id": budget.id, "category": budget.category, "month": start.strftime("%Y-%m"),
            "limit_paise": budget.limit_paise, "spent_paise": amount_spent,
            "remaining_paise": budget.limit_paise - amount_spent,
            "progress_pct": round(amount_spent / budget.limit_paise * 100, 1),
            "is_over_budget": amount_spent > budget.limit_paise,
        })
    return {"month": start.strftime("%Y-%m"), "budgets": result}

@app.post("/api/budgets")
def save_budget(body: BudgetIn, user: User = Depends(employee),
                db: Session = Depends(db_session)):
    start = parse_month(body.month)
    category = body.category.strip()
    if not category:
        raise HTTPException(422, "category cannot be blank")
    row = db.query(Budget).filter(
        Budget.company_id == user.company_id, Budget.user_id == user.id,
        Budget.category == category, Budget.month == start
    ).first()
    if row:
        row.limit_paise = body.limit_paise
    else:
        row = Budget(company_id=user.company_id, user_id=user.id, category=category,
                     month=start, limit_paise=body.limit_paise)
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "category": row.category, "month": start.strftime("%Y-%m"),
            "limit_paise": row.limit_paise, "message": "Budget saved"}

@app.delete("/api/budgets/{budget_id}")
def delete_budget(budget_id: int, user: User = Depends(employee),
                  db: Session = Depends(db_session)):
    row = db.query(Budget).filter(Budget.id == budget_id,
        Budget.company_id == user.company_id, Budget.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "Budget not found")
    db.delete(row)
    db.commit()
    return {"message": "Budget removed"}

@app.get("/api/savings-goals")
def list_savings_goals(user: User = Depends(employee), db: Session = Depends(db_session)):
    goals = db.query(SavingsGoal).filter(
        SavingsGoal.company_id == user.company_id, SavingsGoal.user_id == user.id
    ).order_by(SavingsGoal.created_at.desc()).all()
    return {"goals": [goal_result(goal) for goal in goals]}

@app.post("/api/savings-goals", status_code=201)
def create_savings_goal(body: SavingsGoalIn, user: User = Depends(employee),
                        db: Session = Depends(db_session)):
    row = SavingsGoal(company_id=user.company_id, user_id=user.id,
        name=body.name.strip(), target_paise=body.target_paise, due_date=body.due_date)
    db.add(row)
    db.commit()
    db.refresh(row)
    return goal_result(row)

@app.put("/api/savings-goals/{goal_id}")
def update_savings_goal(goal_id: int, body: SavingsGoalUpdateIn,
                        user: User = Depends(employee), db: Session = Depends(db_session)):
    row = db.query(SavingsGoal).filter(
        SavingsGoal.id == goal_id, SavingsGoal.company_id == user.company_id,
        SavingsGoal.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(404, "Savings goal not found")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(422, "Provide at least one field to update")
    if "name" in updates:
        cleaned = updates["name"].strip()
        if not cleaned:
            raise HTTPException(422, "Goal name cannot be blank")
        row.name = cleaned
    if "target_paise" in updates and updates["target_paise"] is not None:
        row.target_paise = updates["target_paise"]
    if "due_date" in updates:
        row.due_date = updates["due_date"]
    db.commit()
    db.refresh(row)
    return goal_result(row)

@app.delete("/api/savings-goals/{goal_id}")
def delete_savings_goal(goal_id: int, user: User = Depends(employee),
                        db: Session = Depends(db_session)):
    row = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id,
        SavingsGoal.company_id == user.company_id, SavingsGoal.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "Savings goal not found")
    db.query(GoalContribution).filter(GoalContribution.goal_id == row.id,
        GoalContribution.company_id == user.company_id,
        GoalContribution.user_id == user.id).delete()
    db.delete(row)
    db.commit()
    return {"message": "Savings goal removed"}

@app.get("/api/savings-goals/{goal_id}/contributions")
def list_goal_contributions(goal_id: int, user: User = Depends(employee),
                             db: Session = Depends(db_session)):
    goal = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id,
        SavingsGoal.company_id == user.company_id, SavingsGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(404, "Savings goal not found")
    rows = db.query(GoalContribution).filter(
        GoalContribution.goal_id == goal_id, GoalContribution.company_id == user.company_id,
        GoalContribution.user_id == user.id
    ).order_by(GoalContribution.contributed_on.desc(), GoalContribution.id.desc()).all()
    return {"contributions": [{
        "id": row.id, "amount_paise": row.amount_paise, "note": row.note,
        "contributed_on": row.contributed_on.isoformat()
    } for row in rows]}

@app.delete("/api/savings-goals/{goal_id}/contributions/{contribution_id}")
def delete_goal_contribution(goal_id: int, contribution_id: int,
                             user: User = Depends(employee), db: Session = Depends(db_session)):
    goal = db.query(SavingsGoal).filter(
        SavingsGoal.id == goal_id, SavingsGoal.company_id == user.company_id,
        SavingsGoal.user_id == user.id
    ).first()
    if not goal:
        raise HTTPException(404, "Savings goal not found")
    row = db.query(GoalContribution).filter(
        GoalContribution.id == contribution_id, GoalContribution.goal_id == goal_id,
        GoalContribution.company_id == user.company_id, GoalContribution.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(404, "Contribution not found")
    goal.saved_paise = max(0, goal.saved_paise - row.amount_paise)
    db.delete(row)
    db.commit()
    db.refresh(goal)
    return {"goal": goal_result(goal), "message": "Contribution removed"}

@app.post("/api/savings-goals/{goal_id}/contributions", status_code=201)
def contribute_to_goal(goal_id: int, body: GoalContributionIn,
                       user: User = Depends(employee), db: Session = Depends(db_session)):
    goal = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id,
        SavingsGoal.company_id == user.company_id, SavingsGoal.user_id == user.id).first()
    if not goal:
        raise HTTPException(404, "Savings goal not found")
    contribution = GoalContribution(company_id=user.company_id, user_id=user.id,
        goal_id=goal.id, amount_paise=body.amount_paise,
        note=body.note.strip(), contributed_on=body.contributed_on)
    goal.saved_paise += body.amount_paise
    db.add(contribution)
    db.commit()
    db.refresh(goal)
    return {"goal": goal_result(goal), "message": "Contribution recorded"}

@app.get("/api/employer/overview")
def employer_overview(user: User = Depends(employer), db: Session = Depends(db_session)):
    count = db.query(User).filter(User.company_id == user.company_id, User.role == "employee").count()
    if count < MIN_COHORT:
        return {"suppressed": True, "minimum_cohort": MIN_COHORT,
            "employee_count": count, "message": "Cohort insights unlock when the minimum group size is reached."}
    tx_count = db.query(Transaction).filter(Transaction.company_id == user.company_id).count()
    active_count = db.query(func.count(func.distinct(Transaction.user_id))).filter(
        Transaction.company_id == user.company_id).scalar() or 0
    employees_with_budgets = db.query(func.count(func.distinct(Budget.user_id))).filter(
        Budget.company_id == user.company_id).scalar() or 0
    employees_with_savings_goals = db.query(func.count(func.distinct(SavingsGoal.user_id))).filter(
        SavingsGoal.company_id == user.company_id).scalar() or 0
    return {
        "suppressed": False,
        "employee_count": count,
        "employees_with_activity": active_count,
        "employees_with_budgets": employees_with_budgets,
        "employees_with_savings_goals": employees_with_savings_goals,
        "transaction_count": tx_count,
        "activity_rate": round(active_count / count * 100, 1),
        "budget_adoption_rate": round(employees_with_budgets / count * 100, 1),
        "savings_goal_adoption_rate": round(employees_with_savings_goals / count * 100, 1),
        "privacy_note": "Only cohort-level indicators are returned; no individual records or financial amounts are disclosed."
    }


def require_advisor(user: User = Depends(current_user)) -> User:
    if user.role != "advisor":
        raise HTTPException(403, "FINNAL professional account required")
    return user

def write_audit(db: Session, actor: User, subject: User, action: str):
    db.add(AuditEvent(company_id=actor.company_id, actor_id=actor.id,
        subject_user_id=subject.id, action=action))
    db.commit()

def profile_result(row: Optional[FinancialProfile]) -> dict:
    if not row:
        return {"monthly_essential_paise": 0, "emergency_fund_paise": 0,
            "dependents_count": 0, "risk_appetite": "not_set", "primary_goal": "",
            "share_with_advisor": False, "consent_at": None}
    return {"monthly_essential_paise": row.monthly_essential_paise,
        "emergency_fund_paise": row.emergency_fund_paise,
        "dependents_count": row.dependents_count, "risk_appetite": row.risk_appetite,
        "primary_goal": row.primary_goal, "share_with_advisor": row.share_with_advisor,
        "consent_at": row.consent_at.isoformat() if row.consent_at else None}

def payroll_result(row: PayrollEntry) -> dict:
    gross = row.base_salary_paise + row.other_earnings_paise + row.overtime_paise
    deductions = row.pf_deduction_paise + row.tax_deduction_paise + row.other_deductions_paise
    return {"id": row.id, "month": row.month.strftime("%Y-%m"),
        "base_salary_paise": row.base_salary_paise, "other_earnings_paise": row.other_earnings_paise,
        "overtime_paise": row.overtime_paise, "gross_salary_paise": gross,
        "pf_deduction_paise": row.pf_deduction_paise, "tax_deduction_paise": row.tax_deduction_paise,
        "other_deductions_paise": row.other_deductions_paise, "total_deductions_paise": deductions,
        "net_salary_paise": gross - deductions, "deposited_paise": row.deposited_paise,
        "deposit_date": row.deposit_date.isoformat() if row.deposit_date else None,
        "notes": row.notes, "source": row.source,
        "verification": "employee_entered_unverified"}

def asset_result(row: PortfolioAsset) -> dict:
    return {"id": row.id, "asset_type": row.asset_type, "name": row.name,
        "institution": row.institution, "invested_paise": row.invested_paise,
        "current_value_paise": row.current_value_paise, "risk_band": row.risk_band,
        "as_of_date": row.as_of_date.isoformat()}

@app.post("/api/employer/advisors", status_code=201)
def create_company_advisor(body: AdvisorCreateIn, user: User = Depends(employer),
                           db: Session = Depends(db_session)):
    if db.query(User).filter(func.lower(User.email) == body.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    row = User(company_id=user.company_id, name=body.name.strip(), email=body.email.lower(),
        password_hash=password_hash(body.password), role="advisor")
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "email": row.email, "role": row.role,
        "message": "Professional account created for this company"}

@app.get("/api/financial-profile")
def get_financial_profile(user: User = Depends(employee), db: Session = Depends(db_session)):
    row = db.query(FinancialProfile).filter_by(company_id=user.company_id, user_id=user.id).first()
    return profile_result(row)

@app.put("/api/financial-profile")
def save_financial_profile(body: FinancialProfileIn, user: User = Depends(employee),
                           db: Session = Depends(db_session)):
    if body.risk_appetite not in ("not_set", "conservative", "moderate", "growth"):
        raise HTTPException(422, "Invalid risk appetite")
    row = db.query(FinancialProfile).filter_by(company_id=user.company_id, user_id=user.id).first()
    if not row:
        row = FinancialProfile(company_id=user.company_id, user_id=user.id)
        db.add(row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.consent_at = utcnow_naive() if body.share_with_advisor else None
    db.commit(); db.refresh(row)
    return profile_result(row)

@app.get("/api/payroll")
def list_payroll(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(PayrollEntry).filter_by(company_id=user.company_id, user_id=user.id).order_by(
        PayrollEntry.month.desc()).limit(24).all()
    return {"entries": [payroll_result(row) for row in rows]}

@app.post("/api/payroll", status_code=201)
def save_payroll(body: PayrollIn, user: User = Depends(employee), db: Session = Depends(db_session)):
    month = parse_month(body.month)
    gross = body.base_salary_paise + body.other_earnings_paise + body.overtime_paise
    deductions = body.pf_deduction_paise + body.tax_deduction_paise + body.other_deductions_paise
    if deductions > gross:
        raise HTTPException(422, "Total deductions cannot exceed gross salary")
    if body.deposited_paise > gross - deductions:
        raise HTTPException(422, "Deposited amount cannot exceed calculated net salary")
    row = db.query(PayrollEntry).filter_by(company_id=user.company_id, user_id=user.id, month=month).first()
    values = body.model_dump(exclude={"month"})
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = PayrollEntry(company_id=user.company_id, user_id=user.id, month=month, **values)
        db.add(row)
    db.commit(); db.refresh(row)
    return payroll_result(row)

@app.delete("/api/payroll/{entry_id}")
def delete_payroll(entry_id: int, user: User = Depends(employee), db: Session = Depends(db_session)):
    row = db.query(PayrollEntry).filter_by(id=entry_id, company_id=user.company_id, user_id=user.id).first()
    if not row:
        raise HTTPException(404, "Payroll entry not found")
    db.delete(row); db.commit()
    return {"message": "Payroll entry removed"}

@app.get("/api/portfolio/assets")
def list_portfolio_assets(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(PortfolioAsset).filter_by(company_id=user.company_id, user_id=user.id).order_by(
        PortfolioAsset.updated_at.desc()).all()
    return {"assets": [asset_result(row) for row in rows]}

@app.post("/api/portfolio/assets", status_code=201)
def add_portfolio_asset(body: PortfolioAssetIn, user: User = Depends(employee),
                        db: Session = Depends(db_session)):
    if body.asset_type not in ("mutual_fund", "fixed_deposit", "stocks", "gold", "cash", "other"):
        raise HTTPException(422, "Unsupported asset type")
    if body.risk_band not in ("not_set", "low", "moderate", "high"):
        raise HTTPException(422, "Invalid risk band")
    row = PortfolioAsset(company_id=user.company_id, user_id=user.id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return asset_result(row)

@app.delete("/api/portfolio/assets/{asset_id}")
def delete_portfolio_asset(asset_id: int, user: User = Depends(employee), db: Session = Depends(db_session)):
    row = db.query(PortfolioAsset).filter_by(id=asset_id, company_id=user.company_id, user_id=user.id).first()
    if not row:
        raise HTTPException(404, "Portfolio item not found")
    db.delete(row); db.commit()
    return {"message": "Portfolio item removed"}

@app.get("/api/advisories")
def list_advisories(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(AdvisoryMessage).filter_by(company_id=user.company_id, employee_id=user.id).order_by(
        AdvisoryMessage.created_at.desc()).limit(50).all()
    return {"messages": [{"id": r.id, "title": r.title, "message": r.message, "topic": r.topic,
        "created_at": r.created_at.isoformat(), "read": r.read_at is not None} for r in rows]}

@app.post("/api/advisories/{message_id}/read")
def mark_advisory_read(message_id: int, user: User = Depends(employee), db: Session = Depends(db_session)):
    row = db.query(AdvisoryMessage).filter_by(id=message_id, company_id=user.company_id,
        employee_id=user.id).first()
    if not row:
        raise HTTPException(404, "Advisory not found")
    row.read_at = utcnow_naive(); db.commit()
    return {"message": "Marked as read"}

@app.post("/api/loan-requests", status_code=201)
def create_loan_request(body: LoanRequestIn, user: User = Depends(employee), db: Session = Depends(db_session)):
    profile = db.query(FinancialProfile).filter_by(company_id=user.company_id, user_id=user.id).first()
    if not profile or not profile.share_with_advisor:
        raise HTTPException(403, "Enable consent to share your financial profile with a FINNAL professional before requesting an assessment")
    row = LoanRequest(company_id=user.company_id, employee_id=user.id,
        requested_amount_paise=body.requested_amount_paise, purpose=body.purpose.strip(), notes=body.notes.strip())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "status": row.status, "message": "Request submitted for preliminary review, not approved"}

@app.get("/api/loan-requests")
def list_own_loan_requests(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(LoanRequest).filter_by(company_id=user.company_id, employee_id=user.id).order_by(
        LoanRequest.created_at.desc()).all()
    return {"requests": [{"id": r.id, "requested_amount_paise": r.requested_amount_paise,
        "purpose": r.purpose, "status": r.status, "indicative_amount_paise": r.indicative_amount_paise,
        "advisor_note": r.advisor_note, "created_at": r.created_at.isoformat()} for r in rows]}

@app.get("/api/advisor/employees")
def advisor_employees(user: User = Depends(require_advisor), db: Session = Depends(db_session)):
    rows = db.query(User).join(FinancialProfile, FinancialProfile.user_id == User.id).filter(
        User.company_id == user.company_id, User.role == "employee",
        FinancialProfile.company_id == user.company_id, FinancialProfile.share_with_advisor.is_(True)
    ).order_by(User.name.asc()).all()
    return {"employees": [{"id": r.id, "name": r.name, "email": r.email} for r in rows]}

def advisor_can_access(employee_id: int, advisor_user: User, db: Session) -> User:
    target = db.query(User).filter_by(id=employee_id, company_id=advisor_user.company_id, role="employee").first()
    profile = db.query(FinancialProfile).filter_by(company_id=advisor_user.company_id,
        user_id=employee_id, share_with_advisor=True).first()
    if not target or not profile:
        raise HTTPException(404, "Employee not found or has not consented to professional access")
    return target

@app.get("/api/advisor/employees/{employee_id}")
def advisor_employee_detail(employee_id: int, user: User = Depends(require_advisor),
                            db: Session = Depends(db_session)):
    target = advisor_can_access(employee_id, user, db)
    profile = db.query(FinancialProfile).filter_by(company_id=user.company_id, user_id=target.id).first()
    payroll = db.query(PayrollEntry).filter_by(company_id=user.company_id, user_id=target.id).order_by(
        PayrollEntry.month.desc()).limit(12).all()
    assets = db.query(PortfolioAsset).filter_by(company_id=user.company_id, user_id=target.id).all()
    txs = db.query(Transaction).filter_by(company_id=user.company_id, user_id=target.id).order_by(
        Transaction.occurred_on.desc(), Transaction.id.desc()).limit(100).all()
    budget_rows = db.query(Budget).filter_by(company_id=user.company_id, user_id=target.id).order_by(
        Budget.month.desc(), Budget.category.asc()).limit(36).all()
    budget_data = []
    for budget in budget_rows:
        spent = db.query(func.coalesce(func.sum(Transaction.amount_paise), 0)).filter(
            Transaction.company_id == user.company_id, Transaction.user_id == target.id,
            Transaction.kind == "expense", Transaction.category == budget.category,
            Transaction.occurred_on >= budget.month,
            Transaction.occurred_on < month_after(budget.month)
        ).scalar() or 0
        budget_data.append({"category": budget.category, "month": budget.month.strftime("%Y-%m"),
            "limit_paise": budget.limit_paise, "spent_paise": int(spent),
            "remaining_paise": budget.limit_paise - int(spent)})
    write_audit(db, user, target, "advisor_viewed_financial_profile")
    return {"employee": {"id": target.id, "name": target.name, "email": target.email},
        "profile": profile_result(profile), "payroll": [payroll_result(row) for row in payroll],
        "assets": [asset_result(row) for row in assets], "budgets": budget_data,
        "transactions": [{"description": x.description, "amount_paise": x.amount_paise,
            "kind": x.kind, "category": x.category, "occurred_on": x.occurred_on.isoformat()} for x in txs],
        "cashflow": {"transactions": len(txs),
            "income_paise": sum(x.amount_paise for x in txs if x.kind == "income"),
            "expense_paise": sum(x.amount_paise for x in txs if x.kind == "expense")}}

@app.post("/api/advisor/employees/{employee_id}/advisories", status_code=201)
def create_advisory(employee_id: int, body: AdvisoryIn, user: User = Depends(require_advisor),
                    db: Session = Depends(db_session)):
    target = advisor_can_access(employee_id, user, db)
    row = AdvisoryMessage(company_id=user.company_id, employee_id=target.id, advisor_id=user.id,
        title=body.title.strip(), message=body.message.strip(), topic=body.topic)
    db.add(row); db.add(AuditEvent(company_id=user.company_id, actor_id=user.id,
        subject_user_id=target.id, action="advisor_sent_guidance")); db.commit(); db.refresh(row)
    return {"id": row.id, "message": "Guidance saved for the employee"}

@app.get("/api/advisor/loan-requests")
def advisor_loan_requests(user: User = Depends(require_advisor), db: Session = Depends(db_session)):
    rows = db.query(LoanRequest).join(FinancialProfile, FinancialProfile.user_id == LoanRequest.employee_id).filter(
        LoanRequest.company_id == user.company_id, FinancialProfile.company_id == user.company_id,
        FinancialProfile.share_with_advisor.is_(True)
    ).order_by(LoanRequest.created_at.asc()).all()
    return {"requests": [{"id": r.id, "employee_id": r.employee_id,
        "employee_name": db.query(User.name).filter(User.id == r.employee_id).scalar(),
        "requested_amount_paise": r.requested_amount_paise, "purpose": r.purpose, "notes": r.notes,
        "status": r.status, "indicative_amount_paise": r.indicative_amount_paise,
        "advisor_note": r.advisor_note, "created_at": r.created_at.isoformat()} for r in rows]}

@app.patch("/api/advisor/loan-requests/{request_id}")
def review_loan_request(request_id: int, body: LoanReviewIn, user: User = Depends(require_advisor),
                        db: Session = Depends(db_session)):
    allowed = ("under_review", "refer_to_lender", "not_proceeding")
    if body.status not in allowed:
        raise HTTPException(422, "Status must be under_review, refer_to_lender or not_proceeding")
    row = db.query(LoanRequest).filter_by(id=request_id, company_id=user.company_id).first()
    if not row:
        raise HTTPException(404, "Loan request not found")
    advisor_can_access(row.employee_id, user, db)
    if body.indicative_amount_paise is not None and body.indicative_amount_paise > row.requested_amount_paise:
        raise HTTPException(422, "Indicative amount cannot exceed requested amount")
    row.status = body.status
    row.indicative_amount_paise = body.indicative_amount_paise
    row.advisor_note = body.advisor_note.strip()
    row.reviewed_by = user.id; row.reviewed_at = utcnow_naive()
    db.add(AuditEvent(company_id=user.company_id, actor_id=user.id,
        subject_user_id=row.employee_id, action="advisor_reviewed_credit_request"))
    db.commit()
    return {"id": row.id, "status": row.status, "message": "Preliminary assessment saved; this is not a loan approval"}


static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")
