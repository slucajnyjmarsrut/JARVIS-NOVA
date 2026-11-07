# -*- coding: utf-8 -*-
"""Local routing of clear Java/Roblox coding requests (not arbitrary chat).

A voice request only OPENS a review window. It never silently writes files.
"""
from __future__ import annotations
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CodingIntent:
    language: str
    task: str


_WAKE = re.compile(r'^\s*(?:(?:эй|окей|слушай)[,\s]+)?(?:джарвис|жарвис|джервис)[,!\s:;—-]+', re.I)
_DO = re.compile(r'\b(?:напиши|создай|сделай|сгенерируй|разработай|запрограммируй|помоги|открой)\b', re.I)
_JAVA = re.compile(r'\b(?:java|джава|джав[аеы]|javac)\b', re.I)
_LUAU = re.compile(r'\b(?:roblox|роблокс(?:е|а|у)?|luau|lua|роблокс\s+студио)\b', re.I)
_CODE = re.compile(r'\b(?:код|программ|скрипт|проект|игр[ауые]|плагин|бот|класс|мод)\w*\b', re.I)
_NEG = re.compile(r'\b(?:не\s+(?:пиши|создавай|делай|генерируй|запускай|открывай)|отмена|прекрати|стоп)\b', re.I)


def detect_coding_intent(text: str) -> CodingIntent | None:
    if not isinstance(text, str) or not 2 <= len(text) <= 1200:
        return None
    clean = _WAKE.sub('', text.strip(), count=1)
    if _NEG.search(clean) or not _DO.search(clean):
        return None
    has_java, has_luau = bool(_JAVA.search(clean)), bool(_LUAU.search(clean))
    if has_java == has_luau:  # don't arbitrarily choose between both languages
        return None
    if re.match(r'^открой\s+', clean, re.I) and not re.search(r'\b(?:программирование|редактор\s+кода|кодовый\s+помощник)\b', clean, re.I):
        return None
    if not _CODE.search(clean) and not re.match(r'^помоги.*', clean, re.I):
        return None
    return CodingIntent('java' if has_java else 'luau', clean[:700])
