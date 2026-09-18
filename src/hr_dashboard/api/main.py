from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from hr_dashboard.api.routers import chat, pages, profile_ai

app = FastAPI(title="HR Dashboard")

app.mount("/static", StaticFiles(directory="src/hr_dashboard/static"), name="static")
app.include_router(pages.router)
app.include_router(chat.router)
app.include_router(profile_ai.router)
