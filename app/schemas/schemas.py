from pydantic import BaseModel, Field, constr, validator
from datetime import date, datetime
from typing import Optional

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
