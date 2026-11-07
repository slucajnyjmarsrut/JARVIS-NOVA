# -*- coding: utf-8 -*-
"""Text-only coding intents for 20 languages, including Roblox models and maps.

Only OPENS a preview window; never runs model code or silently writes files.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from code_languages import ALIASES


@dataclass(frozen=True)
class CodingIntent:
    language: str
    task: str


_WAKE = re.compile(r'^\s*(?:(?:эй|окей|слушай)[,\s]+)?(?:джарвис|жарвис|джервис)[,!\s:;—-]+', re.I)
_DO = re.compile(r'\b(?:напиши|создай|сделай|сгенерируй|разработай|запрограммируй|помоги|открой)\b', re.I)
_JAVA = re.compile(r'\b(?:java|джава|джав[аеы]|javac)\b', re.I)
_LUAU = re.compile(r'\b(?:roblox|роблокс(?:е|а|у)?|luau|lua|роблокс\s+студио)\b', re.I)
_CODE = re.compile(r'\b(?:код|программ|скрипт|проект|игр[ауые]|плагин|бот|класс|модел|карт|мир|сайт|приложен|сервер|api|база)\w*\b', re.I)
_NEG = re.compile(r'\b(?:не\s+(?:пиши|создавай|делай|генерируй|запускай|открывай)|отмена|прекрати|стоп)\b', re.I)


def detect_coding_intent(text: str) -> CodingIntent | None:
    if not isinstance(text, str) or not 2 <= len(text) <= 1200:
        return None
    clean = _WAKE.sub('', text.strip(), count=1)
    if _NEG.search(clean) or not _DO.search(clean):
        return None
    words=set()
    for alias,language in ALIASES.items():
        if alias in ('c','си','go','го','r','lua'):
            # Single-letter and ambiguous terms only when clearly named as a
            # programming language. Avoid accidental routing from ordinary text.
            continue
        if re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',clean,re.I):
            words.add(language)
    if _JAVA.search(clean):
        words.add('java')
    if _LUAU.search(clean):
        words.add('luau')
    if re.search(r'(?<!\w)c\+\+(?!\w)',clean,re.I):
        words.add('cpp')
    if re.search(r'(?<!\w)c#(?!\w)',clean,re.I):
        words.add('csharp')
    if len(words)!=1:
        return None
    language=next(iter(words))
    if re.match(r'^открой\s+', clean, re.I) and not re.search(r'\b(?:программирование|редактор\s+кода|кодовый\s+помощник)\b', clean, re.I):
        return None
    if not _CODE.search(clean) and not re.match(r'^помоги.*', clean, re.I):
        return None
    return CodingIntent(language, clean[:700])
