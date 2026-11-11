# -*- coding: utf-8 -*-
"""Opt-in adversarial *discussion*, not automatic disagreement or actions.

Commands are exact full utterances so casual references cannot toggle
the mode accidentally. State is session-only and provider-neutral.
"""
from __future__ import annotations
import re

DEBATE_INSTRUCTIONS = (
    "\nРЕЖИМ ДИСКУССИИ (включён пользователем). "
    "Будь внимательным оппонентом, а не соглашателем: предложи лучший "
    "обоснованный контраргумент, укажи на слабые места тезиса и задай "
    "один содержательный вопрос, если это полезно. "
    "Не спорь ради спора: признавай сильные доводы, ошибки и фактическую "
    "правоту пользователя. Отделяй факты от оценок и не выдумывай "
    "источники, эксперименты или доступ к интернету. "
    "Будь вежливым; не используй оскорбления, провокации или унижение. "
    "Если запрос касается безопасности, здоровья либо рискованных действий, "
    "не изображай опасный совет как равнозначную позицию. "
    "Режим меняет только стиль диалога: не исполняй команды и не "
    "ослабляй требования согласия на действия."
)
_ON = frozenset({
    "давай поспорим", "поспорь со мной", "спорь со мной",
    "включи режим спора", "включи режим дебатов",
    "начни спор", "давай подискутируем",
})
_OFF = frozenset({
    "хватит спорить", "не спорь со мной", "прекрати спор",
    "выключи режим спора", "отключи режим спора",
    "закончим спор", "верни обычный режим",
})
_STATUS = frozenset({
    "режим спора", "режим спора включен", "режим спора активен",
    "какой сейчас режим спора",
})

def debate_command(text: str) -> str | None:
    """Return 'on', 'off', 'status' for explicit standalone commands only."""
    if not isinstance(text, str) or not 1 <= len(text) <= 180:
        return None
    normalized = re.sub(r"[\s.,!?;:…]+", " ", text.casefold().replace("ё", "е")).strip()
    normalized = re.sub(
        r"^(?:(?:эй|слушай|привет) )?(?:джарвис|жарвис|джервис|гарвис) ",
        "", normalized, count=1)
    if normalized in _ON:
        return "on"
    if normalized in _OFF:
        return "off"
    if normalized in _STATUS:
        return "status"
    return None
