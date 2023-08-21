from fastapi import FastAPI

from app.api import endpoints
from app.lifespan import lifespan

app = FastAPI(lifespan=lifespan, title="csp0")
app.include_router(endpoints.router)
