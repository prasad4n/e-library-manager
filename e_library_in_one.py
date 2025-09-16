
from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, constr, validator
from sqlalchemy import (create_engine, Column, Integer, String, Date, DateTime, Boolean, ForeignKey,
                        func, Index)
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
import csv
import io
import os
import logging
import tempfile

# -----------------------------
# Configuration & Logging
# -----------------------------
DATABASE_URL = os.getenv("ELIB_DB", "sqlite:///./elibrary.db")
LOG_LEVEL = os.getenv("ELIB_LOG", "INFO")

logging.basicConfig(level=LOG_LEVEL,
                    format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("elibrary")

# -----------------------------
# Database setup (SQLAlchemy)
# -----------------------------
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# -----------------------------
# Models (ORM)
# -----------------------------
class Book(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False, index=True)
    isbn = Column(String, unique=True, index=True, nullable=True)
    published_date = Column(Date, nullable=True)
    copies_total = Column(Integer, default=1)
    copies_available = Column(Integer, default=1, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    loans = relationship("Loan", back_populates="book")

# Create an index to accelerate searches on title/author
Index('ix_books_title_author', Book.title, Book.author)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    joined_at = Column(DateTime, default=datetime.utcnow)

    loans = relationship("Loan", back_populates="user")

class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    book_id = Column(Integer, ForeignKey("books.id"), index=True)
    borrowed_at = Column(DateTime, default=datetime.utcnow)
    due_date = Column(Date)
    returned_at = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True, index=True)

    user = relationship("User", back_populates="loans")
    book = relationship("Book", back_populates="loans")

# -----------------------------
# Pydantic Schemas
# -----------------------------
class BookBase(BaseModel):
    title: constr(min_length=1)
    author: constr(min_length=1)
    isbn: Optional[str] = None
    published_date: Optional[date]
    copies_total: int = Field(default=1, ge=0)

    @validator('copies_total')
    def ensure_non_negative_copies(cls, v):
        if v < 0:
            raise ValueError('copies_total must be >= 0')
        return v

class BookCreate(BookBase):
    pass

class BookUpdate(BaseModel):
    title: Optional[str]
    author: Optional[str]
    isbn: Optional[str]
    published_date: Optional[date]
    copies_total: Optional[int]

class BookOut(BookBase):
    id: int
    copies_available: int
    created_at: datetime

    class Config:
        orm_mode = True

class UserBase(BaseModel):
    name: constr(min_length=1)
    email: constr(min_length=5)

class UserCreate(UserBase):
    pass

class UserOut(UserBase):
    id: int
    joined_at: datetime

    class Config:
        orm_mode = True

class LoanOut(BaseModel):
    id: int
    user_id: int
    book_id: int
    borrowed_at: datetime
    due_date: date
    returned_at: Optional[datetime]
    active: bool

    class Config:
        orm_mode = True

# -----------------------------
# Utility: DB dependency
# -----------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title="E-Library Management API - Demo (FastAPI + SQLite)")

# Create tables on startup if they don't exist (simple approach for demos)
@app.on_event("startup")
def on_startup():
    logger.info("Creating database tables (if not present)...")
    Base.metadata.create_all(bind=engine)

# -----------------------------
# CR(U)D: Books
# -----------------------------
@app.post("/books/", response_model=BookOut)
def create_book(book_in: BookCreate, db: Session = Depends(get_db)):
    # check ISBN uniqueness if provided
    if book_in.isbn:
        existing = db.query(Book).filter(Book.isbn == book_in.isbn).first()
        if existing:
            raise HTTPException(status_code=400, detail="ISBN already exists")
    book = Book(
        title=book_in.title.strip(),
        author=book_in.author.strip(),
        isbn=book_in.isbn,
        published_date=book_in.published_date,
        copies_total=book_in.copies_total,
        copies_available=book_in.copies_total,
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    logger.info(f"Created book id={book.id} title={book.title}")
    return book

@app.get("/books/{book_id}", response_model=BookOut)
def read_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book

@app.put("/books/{book_id}", response_model=BookOut)
def update_book(book_id: int, book_upd: BookUpdate, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    data = book_upd.dict(exclude_unset=True)
    # If copies_total changes, adjust copies_available accordingly (simple policy)
    if 'copies_total' in data:
        delta = data['copies_total'] - book.copies_total
        book.copies_available = max(0, book.copies_available + delta)
        book.copies_total = data['copies_total']
        del data['copies_total']
    for k, v in data.items():
        setattr(book, k, v)
    db.add(book)
    db.commit()
    db.refresh(book)
    logger.info(f"Updated book id={book.id}")
    return book

@app.delete("/books/{book_id}")
def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    # prevent deletion when active loans exist
    active_loans = db.query(Loan).filter(Loan.book_id == book.id, Loan.active == True).count()
    if active_loans > 0:
        raise HTTPException(status_code=400, detail="Cannot delete book with active loans")
    db.delete(book)
    db.commit()
    logger.info(f"Deleted book id={book_id}")
    return {"ok": True}

# Search + pagination
@app.get("/books/", response_model=List[BookOut])
def list_books(q: Optional[str] = Query(None, description="search title or author"),
               author: Optional[str] = None,
               isbn: Optional[str] = None,
               skip: int = 0, limit: int = 20,
               db: Session = Depends(get_db)):
    query = db.query(Book)
    if q:
        like_q = f"%{q}%"
        query = query.filter((Book.title.ilike(like_q)) | (Book.author.ilike(like_q)))
    if author:
        query = query.filter(Book.author.ilike(f"%{author}%"))
    if isbn:
        query = query.filter(Book.isbn == isbn)
    query = query.order_by(Book.title).offset(skip).limit(limit)
    results = query.all()
    return results

# -----------------------------
# Users
# -----------------------------
@app.post("/users/", response_model=UserOut)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(name=user_in.name.strip(), email=user_in.email.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Created user id={user.id} email={user.email}")
    return user

@app.get("/users/{user_id}", response_model=UserOut)
def read_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/users/", response_model=List[UserOut])
def list_users(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return db.query(User).order_by(User.name).offset(skip).limit(limit).all()

# -----------------------------
# Loans (borrow & return)
# -----------------------------
@app.post("/loans/borrow", response_model=LoanOut)
def borrow_book(user_id: int, book_id: int, days: int = 14, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    book = db.query(Book).filter(Book.id == book_id).with_for_update().first()
    if not user or not book:
        raise HTTPException(status_code=404, detail="User or Book not found")
    if book.copies_available < 1:
        raise HTTPException(status_code=400, detail="No copies available")
    # create loan
    due = date.today() + timedelta(days=days)
    loan = Loan(user_id=user.id, book_id=book.id, due_date=due, active=True)
    book.copies_available -= 1
    db.add(loan)
    db.add(book)
    db.commit()
    db.refresh(loan)
    logger.info(f"User {user.id} borrowed book {book.id} loan {loan.id}")
    return loan

@app.post("/loans/return/{loan_id}", response_model=LoanOut)
def return_book(loan_id: int, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    if not loan.active:
        raise HTTPException(status_code=400, detail="Loan already closed")
    loan.returned_at = datetime.utcnow()
    loan.active = False
    # increment available copies
    book = db.query(Book).filter(Book.id == loan.book_id).first()
    if book:
        book.copies_available = min(book.copies_total, book.copies_available + 1)
        db.add(book)
    db.add(loan)
    db.commit()
    db.refresh(loan)
    logger.info(f"Loan {loan_id} returned")
    return loan

@app.get("/loans/", response_model=List[LoanOut])
def list_loans(active: Optional[bool] = None, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(Loan).order_by(Loan.borrowed_at.desc())
    if active is not None:
        query = query.filter(Loan.active == active)
    return query.offset(skip).limit(limit).all()

# -----------------------------
# Batch import (ETL-style) and Export
# -----------------------------
@app.post("/import/books/csv")
def import_books_csv(file: UploadFile = File(...), background_tasks: BackgroundTasks = None, db: Session = Depends(get_db)):
    """
    Accepts CSV with headers: title,author,isbn,published_date,copies_total
    This endpoint demonstrates a simple ingestion pattern. For large files, you'd stream and
    use chunked commits; here it's sufficient for demo purposes.
    """
    content = file.file.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    errors = []
    for i, row in enumerate(reader, start=1):
        try:
            title = row.get('title') or row.get('Title')
            author = row.get('author') or row.get('Author')
            isbn = row.get('isbn') or row.get('ISBN')
            pd_str = row.get('published_date')
            copies = int(row.get('copies_total') or 1)
            pd = None
            if pd_str:
                try:
                    pd = date.fromisoformat(pd_str)
                except Exception:
                    # try common format
                    pd = datetime.strptime(pd_str, "%Y-%m-%d").date()
            # upsert by ISBN if present
            if isbn:
                book = db.query(Book).filter(Book.isbn == isbn).first()
                if book:
                    # update minimal fields
                    book.title = title or book.title
                    book.author = author or book.author
                    book.copies_total = max(book.copies_total, copies)
                    book.copies_available = max(book.copies_available, copies)
                    db.add(book)
                else:
                    book = Book(title=title, author=author, isbn=isbn, published_date=pd,
                                copies_total=copies, copies_available=copies)
                    db.add(book)
            else:
                book = Book(title=title, author=author, published_date=pd,
                            copies_total=copies, copies_available=copies)
                db.add(book)
            created += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})
    db.commit()
    return {"created": created, "errors": errors}

@app.get("/export/analytics/csv")
def export_analytics_csv(db: Session = Depends(get_db)):
    """Export simple analytics: top borrowed books, active loans, counts"""
    # top borrowed books (by number of loans)
    rows = db.query(Book.title, Book.author, func.count(Loan.id).label('borrow_count')).join(Loan).group_by(Book.id).order_by(func.count(Loan.id).desc()).limit(50).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['title', 'author', 'borrow_count'])
    for r in rows:
        writer.writerow([r[0], r[1], r[2]])
    output.seek(0)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    tmp.write(output.getvalue().encode('utf-8'))
    tmp.flush()
    tmp.close()
    return FileResponse(tmp.name, media_type='text/csv', filename='analytics_top_borrowed.csv')

# -----------------------------
# Metrics & Analytics endpoints
# -----------------------------
@app.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    total_books = db.query(func.count(Book.id)).scalar()
    total_users = db.query(func.count(User.id)).scalar()
    active_loans = db.query(func.count(Loan.id)).filter(Loan.active == True).scalar()
    overdue = db.query(func.count(Loan.id)).filter(Loan.active == True, Loan.due_date < date.today()).scalar()
    top_borrowed = db.query(Book.title, func.count(Loan.id).label('cnt')).join(Loan).group_by(Book.id).order_by(func.count(Loan.id).desc()).limit(5).all()
    top = [{'title': t[0], 'count': t[1]} for t in top_borrowed]
    return {
        'total_books': total_books,
        'total_users': total_users,
        'active_loans': active_loans,
        'overdue_loans': overdue,
        'top_borrowed': top,
    }

# -----------------------------
# Simple health check + docs
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

# -----------------------------
# CLI utilities when run directly (small ETL tasks)
# -----------------------------
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='E-Library small utilities')
    parser.add_argument('--initdb', action='store_true', help='Create tables')
    parser.add_argument('--seed', action='store_true', help='Seed sample data')
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    if args.seed:
        db = SessionLocal()
        try:
            # quick idempotent seed
            if db.query(User).count() == 0:
                db.add_all([
                    User(name='Alice', email='alice@example.com'),
                    User(name='Bob', email='bob@example.com')
                ])
            if db.query(Book).count() == 0:
                db.add_all([
                    Book(title='Data Engineering with Python', author='J. Reader', isbn='978-1111111111', copies_total=3, copies_available=3),
                    Book(title='Designing Data-Intensive Applications', author='Martin Kleppmann', isbn='978-0980000000', copies_total=2, copies_available=2),
                ])
            db.commit()
            logger.info('Seeded sample data')
        finally:
            db.close()
    print('Done')
