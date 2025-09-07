from fastapi import FastAPI
from routes import router
from database import init_databases

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    init_databases()

app.include_router(router)
