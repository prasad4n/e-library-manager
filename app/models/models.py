from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

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
