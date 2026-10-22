# -*- coding: utf-8 -*-
"""Post-montage reviewer and bounded automatic recut (offline after rendering).

This module compares a FINAL rendered MP4 against transparent technical and
storyboard checks. If a channel CSV was explicitly imported, it also reports
HISTORICAL view metrics of past videos, never predicted future views.

It can make at most two safer pacing/caption revisions and renders each to a
NEW file, preserving every previous attempt. It cannot measure actual future
CTR, retention, semantic relevance of online clips or guaranteed popularity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
import threading

from channel_audience import AudienceProfile, title_tokens
from viral_studio import Brief, Shot, render_video, validate_brief
from video_forecast import FinalReview, evaluate_final_cut
from video_quality_gate import audit_finished_media

MAX_REVISIONS = 2


class MontageReviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditAttempt:
    number: int
    file: str
    score: int
    structure_score: int
    media_penalty: int
    media_checked: bool
    issues: tuple[str, ...]
    actual_seconds: float
    audience_index: int | None


@dataclass(frozen=True)
class MontageOutcome:
    output: Path
    brief: Brief
    rendered: dict
    review: FinalReview | None
    attempts: tuple[EditAttempt, ...]
    report: Path
    speech: str


def _score_structure(brief: Brief, duration: float) -> tuple[int, tuple[str, ...]]:
    """Diagnostic edit-structure score, NOT a prediction of views or audience."""
    if not math.isfinite(duration) or duration <= 0:
        raise MontageReviewError("Отсутствует корректная длительность монтажа")
    score = 40
    problems: list[str] = []
    if brief.shots[0].seconds <= 3.5:
        score += 18
    else:
        problems.append("Первый кадр длиннее 3,5 секунд")
    if duration <= 60:
        score += 12
    else:
        problems.append("Общая длительность превышает 60 секунд")
    if duration / len(brief.shots) <= 6:
        score += 16
    else:
        problems.append("Медленный монтаж: более 6 секунд на сцену")
    if all(len(s.caption.strip()) <= 55 for s in brief.shots):
        score += 14
    else:
        problems.append("Слишком длинные титры")
    return min(100,score),tuple(problems)


def revised_brief(brief: Brief) -> Brief | None:
    """Improve only verifiable pace/caption defects; never invent new footage."""
    validate_brief(brief)
    changed = False
    shots = []
    for i, shot in enumerate(brief.shots):
        seconds = min(float(shot.seconds),3.0 if i == 0 else 6.0)
        seconds = max(1.0,round(seconds,2))
        caption = " ".join(shot.caption.split())
        if len(caption) > 55:
            # Truncate on word boundary; no transcription or hallucinated words.
            caption = caption[:55].rsplit(" ",1)[0].rstrip(" ,.;:")
            if not caption:
                caption = shot.caption[:54].rstrip()+"…"
        if seconds != shot.seconds or caption != shot.caption:
            changed = True
        shots.append(Shot(seconds, shot.film, caption))
    if not changed:
        return None
    return validate_brief(replace(brief,shots=tuple(shots),
                                  generator=brief.generator+"; локальная правка темпа и титров"))


def _historical(profile: AudienceProfile | None, brief: Brief) -> dict:
    if profile is None:
        return {"status":"no_channel_csv","sample_size":0,
                "typical_views":None,"comparable_count":0,
                "historical_view_band":None,"median_retention_pct":None,
                "median_ctr_pct":None}
    words=set(title_tokens(brief.topic))
    matches=[v for v in profile.videos if words & set(title_tokens(v.title))]
    matched_views=sorted(v.views for v in matches)
    band=None
    if len(matched_views)>=3:
        band=[matched_views[int((len(matched_views)-1)*.25)],
              matched_views[int((len(matched_views)-1)*.75)]]
    retention=[v.avg_view_pct for v in matches if v.avg_view_pct is not None]
    ctr=[v.ctr for v in matches if v.ctr is not None]
    return {"status":"historical_only","sample_size":profile.sample_size,
            "typical_views":profile.typical_views,
            "comparable_count":len(matches),
            "historical_view_band":band,
            "median_retention_pct":round(median(retention),1) if len(retention)>=3 else None,
            "median_ctr_pct":round(median(ctr),1) if len(ctr)>=3 else None}


def _speech(historical: dict, attempts: tuple[EditAttempt,...], best: EditAttempt) -> str:
    introduction="Я проверил итоговый ролик по техническим и монтажным признакам. "
    if historical["historical_view_band"] is not None:
        a,b=historical["historical_view_band"]
        introduction+=(f"Похожие прошлые ролики канала набирали от {a} до {b} "
                       "просмотров. Это история, не прогноз нового видео. ")
    elif historical["status"]=="historical_only":
        introduction+="Данных похожих видео недостаточно для числового ориентира просмотров. "
    else:
        introduction+="Без статистики канала предсказать просмотры невозможно. "
    if best.number>1:
        introduction+=f"Я сделал {len(attempts)-1} повторный монтаж и выбрал более удачный вариант. "
    elif len(attempts)>1:
        introduction+="Я проверил повторный вариант, но исходный оказался не хуже. "
    else:
        introduction+="Повторный монтаж не нужен по проверенным критериям. "
    return introduction+"Проверь смысл кадров и результат перед публикацией."


def analyze_and_recut(
    brief: Brief, footage_dir: Path, project_dir: Path, *,
    profile: AudienceProfile | None = None,
    filename: str = "JARVIS_NOVA_AUTO_VERTICAL.mp4",
    cancel: threading.Event | None = None,
    max_revisions: int = MAX_REVISIONS,
    renderer=None,
    reviewer=None,
    media_auditor=None,
) -> MontageOutcome:
    """Render, assess, recut if actionable, reassess, keep highest-scoring version.

    No network requests or code execution. Existing files are never overwritten.
    Reviewer is invoked with the ACTUAL rendered MP4, not a hypothetical script.
    """
    validate_brief(brief)
    if filename not in ("JARVIS_NOVA_AUTO_VERTICAL.mp4","JARVIS_NOVA_VERTICAL.mp4"):
        raise ValueError("Неизвестное имя файла экспорта")
    if not isinstance(max_revisions,int) or not 0<=max_revisions<=MAX_REVISIONS:
        raise ValueError("Повторный монтаж ограничен двумя попытками")
    project_dir=Path(project_dir)
    footage_dir=Path(footage_dir)
    # Fail before rendering if a previous review exists. Preserve user
    # reports and avoid orphaned new MP4 variants on a repeated click.
    if any((project_dir/name).exists() for name in
           ("POST_MONTAGE_REVIEW.json","POST_MONTAGE_REVIEW_RU.md")):
        raise MontageReviewError("Отчёт предыдущего монтажа уже существует; создай новый проект")
    render=renderer or render_video
    evaluate=reviewer or evaluate_final_cut
    records: list[EditAttempt] = []
    errors: list[str] = []
    versions: list[tuple[Brief,Path,dict,FinalReview | None]] = []
    audits: list[dict] = []
    current=brief
    for attempt in range(max_revisions+1):
        if cancel is not None and cancel.is_set():
            raise MontageReviewError("Монтаж отменён")
        suffix="" if attempt==0 else f"_V{attempt+1}"
        path=project_dir/(Path(filename).stem+suffix+".mp4")
        try:
            rendered=render(current,footage_dir,path,cancel=cancel)
        except Exception as exc:
            if attempt==0 or (cancel is not None and cancel.is_set()):
                raise
            errors.append("Повторная обработка не завершилась: "+type(exc).__name__)
            break
        # Actual FFmpeg renderer verifies H264/AAC/vertical and duration.
        try:
            duration=float(rendered.get("duration",float("nan")))
        except (ValueError,TypeError,AttributeError,OverflowError) as exc:
            raise MontageReviewError("Монтаж не подтвердил правильную длительность") from exc
        if not math.isfinite(duration):
            raise MontageReviewError("Монтаж не подтвердил правильную длительность")
        if rendered.get("technical_quality",{}).get("quality_checked") is not True:
            raise MontageReviewError("Монтаж не прошёл технический контроль FFmpeg")
        structure, problems=_score_structure(current,duration)
        # Real production renders must be inspected. Tests injecting synthetic
        # renderers explicitly inject a media auditor to request quality checks.
        media=None
        audit_note=""
        if renderer is None or media_auditor is not None:
            try:
                media=(media_auditor or audit_finished_media)(path,cancel=cancel)
            except Exception as exc:
                if cancel is not None and cancel.is_set():
                    raise MontageReviewError("Проверка после монтажа отменена") from exc
                audit_note="Дополнительная проверка аудио/видео недоступна: "+type(exc).__name__
        audits.append({
            "version":attempt+1,
            "status":"checked" if media is not None else
                     ("unavailable" if audit_note else "skipped_test_renderer"),
            "warning":audit_note,
            "media":asdict(media) if media is not None else None,
        })
        review=evaluate(current,profile,path,rendered=rendered) if profile is not None else None
        # Audience index is a heuristic, never a probability of views.
        score=round(.65*review.index + .35*structure) if review is not None else structure
        score=max(0,score-(media.penalty if media is not None else 0))
        issues=tuple(problems)+(
            tuple(s for s in review.suggestions if not s.startswith("Просмотри ролик вручную"))
            if review is not None else ()) + (
            tuple(media.warnings) if media is not None else
            ((audit_note,) if audit_note else ()))
        record=EditAttempt(attempt+1,str(path),int(score),int(structure),
                           media.penalty if media is not None else 0,
                           media is not None,
                           issues,round(duration,2),
                           review.index if review is not None else None)
        records.append(record)
        versions.append((current,path,rendered,review))
        if not problems:
            break
        candidate=revised_brief(current)
        if candidate is None:
            break
        # Do not endlessly chase a non-responsive metric, e.g. topic mismatch.
        if len(records)>=2 and records[-1].score<=records[-2].score:
            break
        current=candidate
    # Ties favour actual structure improvement, then earlier versions.
    selected=max(range(len(records)),
                 key=lambda i:(records[i].score,records[i].structure_score,-i))
    chosen=records[selected]
    best_brief,best_path,best_render,best_review=versions[selected]
    history=_historical(profile,brief)
    speech=_speech(history,tuple(records),chosen)
    if errors:
        speech+=" Повторная обработка завершилась ошибкой; сохранён проверенный предыдущий вариант."
    if chosen.media_checked:
        media_alerts=[x for x in chosen.issues if x in (
            audits[selected]["media"] or {}).get("warnings",[])]
        if media_alerts:
            speech+=" По аудио и видео: "+"; ".join(media_alerts[:2])+"."
    elif audits[selected]["status"]=="unavailable":
        speech+=" Видеопроверка кадров и звука не завершилась."
    report={
        "schema":1,"created_utc":datetime.now(timezone.utc).isoformat(),
        "selected_version":chosen.number,
        "chosen_video":str(best_path),
        "attempts":[asdict(x) for x in records],
        "media_audits":audits,
        "revision_errors":errors,
        "historical_channel_data":history,
        "technical_quality":best_render["technical_quality"],
        "viewer_metrics_are_predictions":False,
        "limitations":[
            "Просмотры, CTR и удержание нового ролика до публикации неизвестны.",
            "Исторические значения канала НЕ прогноз и НЕ гарантия просмотров.",
            "Формальный индекс монтажа НЕ проверяет смысл кадров и реакцию аудитории.",
            "Исходные MP4 и предыдущие версии не перезаписываются.",
        ],
        "spoken_feedback":speech,
    }
    project_dir.mkdir(parents=True,exist_ok=True)
    report_path=project_dir/"POST_MONTAGE_REVIEW.json"
    with report_path.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
    readme=project_dir/"POST_MONTAGE_REVIEW_RU.md"
    lines=[
        "# Проверка ролика и автоматические правки","",
        f"Выбран монтаж №{chosen.number}: {best_path.name}",
        f"Оценка по явным признакам: {chosen.score}/100. Это НЕ вероятность просмотров.",
        f"Количество вариантов: {len(records)}",
        f"Проверка аудио/кадров выбранной версии: {audits[selected]['status']}","",
        "## Исторические данные канала (НЕ прогноз)",
        f"Сравнимых роликов: {history['comparable_count']}",
        f"Типичные просмотры канала: {history['typical_views'] if history['typical_views'] is not None else 'нет CSV'}",
        f"Исторический диапазон просмотров: {history['historical_view_band'] or 'недостаточно данных'}",
        f"Медиана удержания похожих роликов: {history['median_retention_pct']}",
        f"Медиана CTR похожих роликов: {history['median_ctr_pct']}","",
        "## Попытки и замечания",
    ]
    for row in records:
        lines.append(f"- Версия {row.number}: {row.score}/100; {row.file}")
        lines.extend("  - "+issue for issue in row.issues)
    lines.extend("Ошибка: "+error for error in errors)
    lines+=["","## Голосовой вывод",speech,"",
            "Ни один результат не публикуется автоматически.",
            "Проверь подбор кадров, авторские права, музыку и субтитры перед публикацией."]
    with readme.open("x",encoding="utf-8") as stream:
        stream.write("\n".join(lines)+"\n")
    return MontageOutcome(best_path,best_brief,best_render,best_review,
                          tuple(records),readme,speech)
