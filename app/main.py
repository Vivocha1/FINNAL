import os, hashlib, hmac, secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from jose import jwt, JWTError
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, ForeignKey, func, text, UniqueConstraint
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

static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")
