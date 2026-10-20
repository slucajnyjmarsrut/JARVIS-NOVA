# -*- coding: utf-8 -*-
"""Exact-match local conversational responses with no model startup.

Only harmless greetings and identity/availability are answered immediately.
No automation, app-launching, deleting, permissions or ambiguous phrases.
"""
from __future__ import annotations
import re


_RESPONSES={
    "привет":"Привет! Я здесь. Чем помочь?",
    "здравствуй":"Привет! Слушаю тебя.",
    "здравствуйте":"Здравствуйте! Чем могу помочь?",
    "как дела":"Всё хорошо. Слушаю тебя, чем помочь?",
    "как твои дела":"Всё хорошо. Готов помочь.",
    "что делаешь":"Слушаю тебя и жду следующую команду.",
    "что ты делаешь":"Слушаю тебя и готов помочь.",
    "ты меня слышишь":"Да, если команда появилась в строке «РАСПОЗНАНО», микрофон работает.",
    "слышишь меня":"Да, я получил твою фразу.",
    "кто ты":"Я JARVIS NOVA, локальный голосовой помощник.",
    "спасибо":"Пожалуйста!",
    "благодарю":"Рад помочь.",
    "пока":"До встречи!",
}


def quick_reply(text: str) -> str | None:
    if not isinstance(text,str):
        return None
    from agent_core import strip_wake
    value=strip_wake(text).lower().replace("ё","е")
    value=re.sub(r"[^а-яa-z0-9\s]"," ",value)
    value=" ".join(value.split())
    return _RESPONSES.get(value)
