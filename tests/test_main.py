import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_create_user_and_book_and_borrow_return():
    # Create user
    user = {"name": "Test User", "email": "test@example.com"}
    r = client.post("/users/", json=user)
    assert r.status_code == 200
    user_id = r.json()["id"]

    # Create book
    book = {"title": "Test Book", "author": "Author", "isbn": "12345", "copies_total": 1}
    r = client.post("/books/", json=book)
    assert r.status_code == 200
    book_id = r.json()["id"]

    # Borrow book
    r = client.post(f"/loans/borrow?user_id={user_id}&book_id={book_id}&days=7")
    assert r.status_code == 200
    loan_id = r.json()["id"]
    assert r.json()["active"] is True

    # Return book
    r = client.post(f"/loans/return/{loan_id}")
    assert r.status_code == 200
    assert r.json()["active"] is False
