# -*- coding: utf-8 -*-
"""Deterministic acceptance checks and bounded local revision of video scripts.

A passed check means structural/storyboard consistency only, not artistic
quality or factual truth. No internet, external accounts, or user footage are
ever used by this module. Fast fallback is honestly labeled non-AI.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import re

from viral_studio import Brief, ViralStudioError, validate_brief
from quick_video_brief import quick_brief


@dataclass(frozen=True)
class ScenarioAssessment:
    passed: bool
    issues: tuple[str, ...]
    seconds: float


def assess_scenario(brief: Brief) -> ScenarioAssessment:
    try:
        validate_brief(brief)
    except (ViralStudioError,ValueError,TypeError) as exc:
        return ScenarioAssessment(False,(str(exc)[:140],),0.)
    issues=[]
    total=sum(s.seconds for s in brief.shots)
    if not 20 <= total <= 50:
        issues.append("Суммарная длительность должна быть 20–50 секунд.")
    if brief.shots[0].seconds>3:
        issues.append("Первый кадр длиннее 3 секунд.")
    if len(brief.shots)<3:
        issues.append("Мало кадров для завязки, развития и финала.")
    if len(brief.script)<85:
        issues.append("Сценарий недостаточно подробный.")
    captions=[s.caption.casefold().strip() for s in brief.shots]
    if len(set(captions))<len(captions):
        issues.append("Повторяются подписи кадров.")
    films=[re.sub(r"\s+"," ",s.film.casefold()).strip() for s in brief.shots]
    if len(set(films))<len(films):
        issues.append("Повторяются инструкции для съёмки.")
    topic_words=[w for w in re.findall(r"[\w]{4,}",brief.topic.casefold())
                 if w not in {"видео","ролик","шортс","создай","сделай"}]
    seen=(" ".join([brief.title,brief.hook,brief.script]+
                   [s.film for s in brief.shots])).casefold()
    if topic_words and not any(word in seen for word in topic_words[:6]):
        issues.append("Тема пользователя не отражена в сценарии.")
    if not brief.call_to_action.strip(" .!?"):
        issues.append("Нет понятного завершения.")
    return ScenarioAssessment(not issues,tuple(issues),total)


def create_checked_scenario(topic, trends=(), *, mode="fast", audience=None,
                            runtime=None, ai_generator=None, max_revisions=2):
    """One call creates a reviewable script, tries local repairs, or falls back.

    Generator is always the local Qwen implementation (or injected fake for
    unit tests), never FreeLLM and never arbitrary discovered model weights.
    Returns (brief, user-facing note, assessment, attempts).
    """
    if mode not in ("fast","standard","deep"):
        raise ValueError("Неизвестный режим сценария.")
    if type(max_revisions) is not int or not 0<=max_revisions<=2:
        raise ValueError("Не больше двух проверяемых повторов.")
    if mode=="fast":
        brief=quick_brief(topic,trends,audience=audience)
        report=assess_scenario(brief)
        return brief,"Быстрый локальный сценарий без нейросети.",report,1
    if ai_generator is None:
        from viral_studio import create_local_brief
        ai_generator=create_local_brief
    kwargs={"audience":audience,
            "timeout_seconds":20 if mode=="standard" else 75,
            "max_tokens":850 if mode=="standard" else 1450}
    if runtime is not None:
        kwargs.update(model_runtime=runtime,stop_runtime=False)
    report=None
    for attempt in range(max_revisions+1):
        try:
            call_kwargs=dict(kwargs)
            if attempt:
                call_kwargs["quality_feedback"]=(
                    "Исправь предыдущую структуру сценария. "
                    +"; ".join(report.issues)[:330]
                    +" Начни с зацепки, сделай разные сцены, конкретный сюжет "
                    "по теме и ясный финал. Не выдумывай факты.")
            brief=ai_generator(topic,trends,**call_kwargs)
            if not isinstance(brief,Brief):
                raise ViralStudioError("ИИ не вернул сценарий.")
            if not brief.generator.startswith("локальная Qwen"):
                raise ViralStudioError("Модель вернула не-ИИ шаблон.")
            if brief.shots and 3 < brief.shots[0].seconds <= 12:
                # Editorial timing adjustment, never invents text or scenes:
                # keep the AI-written hook but show it within 3 seconds.
                first=replace(brief.shots[0],seconds=3.0)
                brief=replace(brief,shots=(first,*brief.shots[1:]))
            report=assess_scenario(brief)
            if report.passed:
                return brief,(
                    f"Сценарий локальной Qwen; формальная проверка пройдена "
                    f"за {attempt+1} попытку(и). Требуется оценить факты и сюжет."
                ),report,attempt+1
        except Exception as exc:
            report=ScenarioAssessment(False,(str(exc)[:160],),0.)
    fallback=quick_brief(topic,trends,audience=audience)
    fallback_report=assess_scenario(fallback)
    return fallback,(
        "Локальная Qwen не подготовила сценарий, прошедший формальные "
        "проверки. Использован авторский шаблон БЕЗ нейросети. "
        "Причины: "+"; ".join(report.issues)[:220]
    ),fallback_report,max_revisions+1
