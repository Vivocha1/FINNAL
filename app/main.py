import os, hashlib, hmac, secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from jose import jwt, JWTError
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, ForeignKey, func, text
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

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    code = Column(String(48), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="employee", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

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

@app.get("/api/overview")
def overview(user: User = Depends(employee), db: Session = Depends(db_session)):
    rows = db.query(Transaction).filter(Transaction.company_id == user.company_id,
        Transaction.user_id == user.id).all()
    income = sum(r.amount_paise for r in rows if r.kind == "income")
    expense = sum(r.amount_paise for r in rows if r.kind == "expense")
    return {"income_paise": income, "expense_paise": expense,
        "net_paise": income - expense, "transaction_count": len(rows)}

@app.get("/api/employer/overview")
def employer_overview(user: User = Depends(employer), db: Session = Depends(db_session)):
    count = db.query(User).filter(User.company_id == user.company_id, User.role == "employee").count()
    if count < MIN_COHORT:
        return {"suppressed": True, "minimum_cohort": MIN_COHORT,
            "employee_count": count, "message": "Cohort insights unlock when the minimum group size is reached."}
    tx_count = db.query(Transaction).filter(Transaction.company_id == user.company_id).count()
    active_count = db.query(func.count(func.distinct(Transaction.user_id))).filter(
        Transaction.company_id == user.company_id).scalar() or 0
    return {"suppressed": False, "employee_count": count, "employees_with_activity": active_count,
        "transaction_count": tx_count, "activity_rate": round(active_count / count * 100, 1),
        "privacy_note": "Only cohort-level indicators are returned; no individual transaction details."}

static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")
