# -*- coding: utf-8 -*-
"""Consent-only discovery of already-running, code-optimized Ollama models.

Unlike filesystem model inventory, this checks the LIVE local Ollama API,
which is the only way to know a discovered model can actually be served.
Never downloads/registers weights; never opens LAN/cloud endpoints.
Returning a candidate does not execute it; CodeWindow may use it only
after the user's upfront approval for a coding session.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request

ENDPOINT="http://127.0.0.1:11434"
ALLOWED_FAMILIES=(
    "qwen2.5-coder", "qwen3-coder", "deepseek-coder",
    "starcoder2", "codestral", "codellama",
)
CODE_NAME=re.compile(
    r"^("+"|".join(re.escape(x) for x in ALLOWED_FAMILIES)
    +r"):(\d{1,2}(?:\.\d)?b)(?:-[a-z0-9._-]{1,24})?$",re.I)
MAX_MODEL_BYTES=12_000_000_000
MAX_BILLIONS=14


@dataclass(frozen=True)
class InstalledCoder:
    name: str
    billions: float
    disk_bytes: int


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RuntimeError("Локальный Ollama попытался перенаправить запрос.")


def _get_tags():
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}),_NoRedirect())
    request=urllib.request.Request(
        ENDPOINT+"/api/tags",method="GET",
        headers={"Accept":"application/json"})
    with opener.open(request,timeout=4) as response:
        result=response.read(200_001)
    if len(result)>200_000:
        raise ValueError("Слишком большой ответ Ollama.")
    return json.loads(result)


def installed_coders(*, confirmed=False, transport=None):
    if confirmed is not True:
        raise PermissionError(
            "Нужно разрешение для обращения к локальной Ollama.")
    response=(transport or _get_tags)()
    if not isinstance(response,dict) or not isinstance(response.get("models"),list):
        raise ValueError("Некорректный список моделей Ollama.")
    candidates={}
    for entry in response["models"][:150]:
        if not isinstance(entry,dict):
            continue
        name=entry.get("name")
        size=entry.get("size")
        if not isinstance(name,str) or type(size) is not int:
            continue
        m=CODE_NAME.fullmatch(name)
        if not m or not 0<size<=MAX_MODEL_BYTES:
            continue
        billions=float(m.group(2)[:-1])
        if billions<1 or billions>MAX_BILLIONS:
            continue
        candidates[name.casefold()]=InstalledCoder(name,billions,size)
    return tuple(sorted(candidates.values(),key=lambda x:(-x.billions,x.name)))


def best_installed_coder(*, confirmed=False, transport=None):
    choices=installed_coders(confirmed=confirmed,transport=transport)
    return choices[0] if choices else None
