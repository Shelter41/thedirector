import logging

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..wiki.query import query as wiki_query

logger = logging.getLogger("thedirector.api.query")

router = APIRouter()


class QueryRequest(BaseModel):
    question: str


@router.post("/query")
async def ask(req: QueryRequest):
    result = await wiki_query(settings.data_root, req.question)
    return result
