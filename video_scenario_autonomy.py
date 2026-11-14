# -*- coding: utf-8 -*-
"""Deterministic acceptance checks and bounded local revision of video scripts.

A passed check means structural/storyboard consistency only, not artistic
quality or factual truth. No internet, external accounts, or user footage are
ever used by this module. Fast fallback is honestly labeled non-AI.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import re

from viral_studio import Brief, ViralStudioError, RejectedScenarioDraft, validate_brief
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
    roles=("hook","setup","action","result","ending")
    def duplicate_pairs(values):
        first={}
        repeated=[]
        for index,value in enumerate(values):
            if value in first:
                original=first[value]
                name=lambda idx: roles[idx] if idx<len(roles) else str(idx+1)
                repeated.append(name(original)+"="+name(index))
            else:
                first[value]=index
        return ", ".join(repeated[:4])
    captions=[s.caption.casefold().strip() for s in brief.shots]
    same_captions=duplicate_pairs(captions)
    if same_captions:
        issues.append("Повторяются подписи кадров ("+same_captions+").")
    films=[re.sub(r"\s+"," ",s.film.casefold()).strip() for s in brief.shots]
    same_films=duplicate_pairs(films)
    if same_films:
        issues.append("Повторяются инструкции для съёмки ("+same_films+").")
    # Match word stems, not literal Russian inflections. For example,
    # "рабочего" and "рабочем", "компьютерного" and "компьютера"
    # describe the same subject. Require a word-boundary match; do not
    # accept an accidental substring in an unrelated compound word.
    stopwords={"видео","ролик","шортс","создай","сделай","хочу",
               "как","для","это","тема","про","мое","мои","наше"}
    topic_words=[w for w in re.findall(r"[^\W_]{3,}",brief.topic.casefold())
                 if w not in stopwords][:8]
    words=set(re.findall(
        r"[^\W_]{3,}",
        (" ".join([brief.title,brief.hook,brief.script]+
                  [s.film for s in brief.shots])).casefold()))
    # Cap stemming to a conservative four trailing characters, rather
    # than silently accepting a completely unrelated story.
    roots=[w[:max(4,len(w)-4)] for w in topic_words]
    if roots and not any(word.startswith(root)
                         for root in roots for word in words):
        issues.append("Тема пользователя не отражена в сценарии.")
    if not brief.call_to_action.strip(" .!?"):
        issues.append("Нет понятного завершения.")
    return ScenarioAssessment(not issues,tuple(issues),total)


def create_checked_scenario(topic, trends=(), *, mode="fast", audience=None,
                            runtime=None, ai_generator=None, max_revisions=2,
                            progress=None):
    """One call creates a reviewable script, tries local repairs, or falls back.

    By default, a separate local Gemma3:4b specialist writes scripts, not
    Qwen Vision. Injection supports controlled regression and legacy tests.
    Returns (brief, user-facing note, assessment, attempts).
    """
    if mode not in ("fast","standard","deep"):
        raise ValueError("Неизвестный режим сценария.")
    if progress is not None and not callable(progress):
        raise ValueError("Нужен корректный обработчик прогресса.")
    def announce(message):
        if progress is not None:
            progress(str(message)[:350])
    announce("План: 1/3 сюжет и зацепка → "
             "2/3 отдельные кадры и подписи → 3/3 итоговая проверка.")
    if type(max_revisions) is not int or not 0<=max_revisions<=2:
        raise ValueError("Не больше двух проверяемых повторов.")
    if mode=="fast":
        announce("Шаг 1/3: составляю сюжет без нейросети…")
        brief=quick_brief(topic,trends,audience=audience)
        announce("Шаг 2/3: готовлю кадры и подписи…")
        report=assess_scenario(brief)
        announce("Шаг 3/3: "+("формат проверен" if report.passed else
                 "найдены замечания: "+"; ".join(report.issues)[:150]))
        return brief,"Быстрый локальный сценарий без нейросети.",report,1
    if ai_generator is None:
        from scenario_specialist import create_specialist_brief
        ai_generator=create_specialist_brief
    kwargs={"audience":audience,
            "timeout_seconds":20 if mode=="standard" else 75,
            "max_tokens":850 if mode=="standard" else 1450}
    if runtime is not None:
        kwargs.update(model_runtime=runtime,stop_runtime=False)
    report=None
    previous=None
    failures=[]
    for attempt in range(max_revisions+1):
        announce("Шаг 1/3: ИИ-сценарист создаёт вариант "+
                 str(attempt+1)+"/"+str(max_revisions+1)+"…")
        try:
            call_kwargs=dict(kwargs)
            if attempt:
                call_kwargs["quality_feedback"]=(
                    "Исправь предыдущую структуру сценария. "
                    +"; ".join(report.issues)[:330]
                    +" Начни с зацепки, сделай разные сцены, конкретный сюжет "
                    "по теме и ясный финал. Не выдумывай факты.")
                if previous is not None:
                    call_kwargs["previous_brief"]=previous
            brief=ai_generator(topic,trends,**call_kwargs)
            if not isinstance(brief,Brief):
                raise ViralStudioError("ИИ не вернул сценарий.")
            if not brief.generator.startswith(("локальная Qwen3-VL","локальная Gemma3:4b")):
                raise ViralStudioError("Модель вернула не-ИИ шаблон.")
            if brief.shots and 3 < brief.shots[0].seconds <= 12:
                # Editorial timing adjustment, never invents text or scenes:
                # keep the AI-written hook but show it within 3 seconds.
                first=replace(brief.shots[0],seconds=3.0)
                brief=replace(brief,shots=(first,*brief.shots[1:]))
            announce("Шаг 2/3: проверяю кадры, подписи и длительность…")
            report=assess_scenario(brief)
            if not report.passed:
                previous=brief
            if report.passed:
                announce("Шаг 3/3: весь сценарий прошёл формальную проверку. "
                         "Факты и художественный результат требуют просмотра.")
                editorial=(
                    " Повторные подписи заменены на фразы из инструкций "
                    "съёмки, написанных той же Qwen."
                    if ("подписи взяты из инструкций ИИ" in brief.generator
                        or "подписи взяты из инструкций Qwen" in brief.generator)
                    else "")
                return brief,(
                    f"Сценарий {brief.generator}; формальная проверка пройдена "
                    f"за {attempt+1} попытку(и). Требуется оценить факты и сюжет."
                    +editorial
                ),report,attempt+1
        except RejectedScenarioDraft as exc:
            # A parseable but invalid AI response can be revised, not accepted.
            previous=exc.draft if 2<=len(exc.draft.shots)<=10 else None
            report=ScenarioAssessment(False,(str(exc)[:160],),0.)
        except Exception as exc:
            report=ScenarioAssessment(False,(str(exc)[:160],),0.)
        if report and not report.passed:
            issues="; ".join(report.issues)[:180]
            failures.append(f"{attempt+1}: "+issues)
            announce("Шаг 2/3: вариант "+str(attempt+1)+
                     " не прошёл проверку: "+issues+
                     ("; исправляю этот вариант" if attempt<max_revisions
                      else "; попытки закончились"))
    announce("Шаг 3/3: ИИ-сценарист не прошёл проверку; "
             "вместо неё будет явно обозначенный шаблон БЕЗ нейросети.")
    fallback=quick_brief(topic,trends,audience=audience)
    fallback_report=assess_scenario(fallback)
    return fallback,(
        "Отдельный ИИ-сценарист не подготовил сценарий, прошедший формальные "
        "проверки. Использован авторский шаблон БЕЗ нейросети. "
        "Причины попыток: "+" | ".join(failures)[-420:]
    ),fallback_report,max_revisions+1
