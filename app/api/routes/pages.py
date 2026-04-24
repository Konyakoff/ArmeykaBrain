"""HTML-страницы (вкладки): /, /text, /audio, /video, /text/{slug}."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
@router.get("/text", response_class=HTMLResponse)
@router.get("/audio", response_class=HTMLResponse)
@router.get("/video", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/text/{slug}", response_class=HTMLResponse)
async def view_result_page(request: Request, slug: str):
    return templates.TemplateResponse(request=request, name="result.html", context={"slug": slug})
