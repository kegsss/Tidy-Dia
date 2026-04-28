from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Optional


PAYLOAD = (
    "JSON.stringify({"
    "metaDesc:document.querySelector('meta[name=description]')?.content||null,"
    "ogTitle:document.querySelector('meta[property=\\\"og:title\\\"]')?.content||null,"
    "ogDesc:document.querySelector('meta[property=\\\"og:description\\\"]')?.content||null,"
    "h1:document.querySelector('h1')?.innerText?.slice(0,200)||null,"
    "selection:getSelection().toString().slice(0,500)||null,"
    "scrollPct:Math.round(scrollY/Math.max(1,(document.body.scrollHeight-innerHeight))*100)||0,"
    "textSample:(document.body&&document.body.innerText||'').slice(0,800),"
    "referrer:document.referrer||null"
    "})"
)


@dataclass
class PageContext:
    meta_desc: Optional[str] = None
    og_title: Optional[str] = None
    og_desc: Optional[str] = None
    h1: Optional[str] = None
    selection: Optional[str] = None
    scroll_pct: int = 0
    text_sample: Optional[str] = None
    referrer: Optional[str] = None


def parse(raw: str) -> PageContext:
    if not raw:
        return PageContext()
    try:
        data = json.loads(raw)
    except Exception:
        return PageContext()
    return PageContext(
        meta_desc=data.get("metaDesc"),
        og_title=data.get("ogTitle"),
        og_desc=data.get("ogDesc"),
        h1=data.get("h1"),
        selection=data.get("selection"),
        scroll_pct=int(data.get("scrollPct") or 0),
        text_sample=data.get("textSample"),
        referrer=data.get("referrer"),
    )
