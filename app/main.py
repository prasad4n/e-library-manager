from fastapi import FastAPI
from app.core.database import Base, engine
from app.api import routes

Base.metadata.create_all(bind=engine)
app = FastAPI(title="E-Library Management System")
app.include_router(routes.router)

@app.get("/health")
def health():
    return {"status": "ok"}
