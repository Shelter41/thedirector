import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .connectors.db import init_pool, close_pool
from .store.wiki import init_knowledgebase

from .api.oauth import router as oauth_router
from .api.ingest import router as ingest_router
from .api.status import router as status_router
from .api.wiki import router as wiki_router
from .api.query import router as query_router
from .api.chat import router as chat_router
from .api.chats import router as chats_router
from .api.dream import router as dream_router
from .api.activity import router as activity_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    # Ensure data directories exist
    Path(settings.data_root).mkdir(parents=True, exist_ok=True)
    (Path(settings.data_root) / "raw").mkdir(exist_ok=True)
    init_knowledgebase(settings.data_root)
    yield
    await close_pool()


app = FastAPI(title="The Director", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(oauth_router)
app.include_router(ingest_router)
app.include_router(status_router)
app.include_router(wiki_router)
app.include_router(query_router)
app.include_router(chat_router)
app.include_router(chats_router)
app.include_router(dream_router)
app.include_router(activity_router)
