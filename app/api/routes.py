from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date, timedelta
import csv, io, tempfile
from fastapi.responses import FileResponse
from sqlalchemy import func

from app.core.database import get_db
from app.models import models
from app.schemas import schemas

router = APIRouter()

@router.post("/books/", response_model=schemas.BookOut)
def create_book(book_in: schemas.BookCreate, db: Session = Depends(get_db)):
    if book_in.isbn:
        existing = db.query(models.Book).filter(models.Book.isbn == book_in.isbn).first()
        if existing:
            raise HTTPException(status_code=400, detail="ISBN already exists")
    book = models.Book(
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
    return book

@router.get("/books/", response_model=List[schemas.BookOut])
def list_books(q: Optional[str] = Query(None), skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    query = db.query(models.Book)
    if q:
        like_q = f"%{q}%"
        query = query.filter((models.Book.title.ilike(like_q)) | (models.Book.author.ilike(like_q)))
    return query.order_by(models.Book.title).offset(skip).limit(limit).all()

@router.post("/users/", response_model=schemas.UserOut)
def create_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(name=user_in.name.strip(), email=user_in.email.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/loans/borrow", response_model=schemas.LoanOut)
def borrow_book(user_id: int, book_id: int, days: int = 14, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not user or not book:
        raise HTTPException(status_code=404, detail="User or Book not found")
    if book.copies_available < 1:
        raise HTTPException(status_code=400, detail="No copies available")
    loan = models.Loan(user_id=user.id, book_id=book.id, due_date=date.today() + timedelta(days=days))
    book.copies_available -= 1
    db.add(loan); db.add(book); db.commit(); db.refresh(loan)
    return loan

@router.post("/loans/return/{loan_id}", response_model=schemas.LoanOut)
def return_book(loan_id: int, db: Session = Depends(get_db)):
    loan = db.query(models.Loan).filter(models.Loan.id == loan_id).first()
    if not loan: raise HTTPException(status_code=404, detail="Loan not found")
    loan.returned_at = datetime.utcnow(); loan.active = False
    book = db.query(models.Book).filter(models.Book.id == loan.book_id).first()
    if book: book.copies_available = min(book.copies_total, book.copies_available + 1); db.add(book)
    db.add(loan); db.commit(); db.refresh(loan)
    return loan
