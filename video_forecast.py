# -*- coding: utf-8 -*-
"""Final AFTER-render audit: true MP4 metadata + user's past channel results.

Score is a heuristic checklist of channel fit. NOT a calibrated chance of virality.
"""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
import json
from pathlib import Path
from channel_audience import tokens
from viral_studio import ViralStudioError,ffmpeg_tools,_probe

@dataclass(frozen=True)
class FinalAssessment:
    index:int
    verdict:str
    confidence:str
    evidence:tuple[str,...]
    advice:tuple[str,...]
    historical_views:tuple[int,int]|None
    comparable_count:int
    duration:float
    output:str

def assess_video(brief,audience,output,*,tools=None):
    """Requires actually rendered MP4, not just a storyboard."""
    output=Path(output)
    if not output.is_file() or output.stat().st_size<1000:
        raise ViralStudioError('Сначала смонтируй настоящее видео MP4')
    if tools is None:tools=ffmpeg_tools()
    duration,audio=_probe(output,tools[1])
    topic=set(tokens(brief.topic))
    repeat=topic&set(audience.winning_topics)
    matches=sorted(v.views for v in audience.videos if tokens(v.title)&topic)
    history=None
    if len(matches)>=3:
        n=len(matches)
        history=(matches[(n-1)//4],matches[(3*n)//4])
    count=len(brief.shots)
    conditions=[
        ('Тема повторяется в лидерах канала',bool(repeat),15),
        ('Формат подходит для короткого вертикального видео',12<=duration<=60,12),
        ('Зацепка в первые 3,5 секунды',bool(count and brief.shots[0].seconds<=3.5 and brief.hook),12),
        ('Монтаж без длинных пауз между сценами',bool(count>=4 and duration/count<=8),8),
        ('Файл имеет аудиодорожку',bool(audio),6),
        ('Короткий текст на экране',all(len(s.caption)<=55 for s in brief.shots),4),
        ('Присутствует призыв к действию',bool(brief.call_to_action.strip()),3)
    ]
    index=max(0,min(100,40+sum(impact for _,ok,impact in conditions if ok)))
    evidence=tuple(f'{"✓" if ok else "×"} {name}' for name,ok,_ in conditions)
    advice=[]
    if not repeat:advice.append('Свяжи ролик с повторяющимися темами лучших видео канала.')
    if duration>60:advice.append('Проверь, можно ли ускорить историю: ролик длиннее минуты.')
    if count and brief.shots[0].seconds>3.5:advice.append('Перенеси результат или интригу в первые три секунды.')
    if not audio:advice.append('В ролике нет аудиодорожки; проверь звук.')
    if any(len(s.caption)>55 for s in brief.shots):
        advice.append('Сделай подписи короче, чтобы их читали с телефона.')
    if not advice:advice.append('Проверь ролик глазами и на телефоне; попробуй два честных заголовка.')
    verdict=('соответствует формальным признакам' if index>=80 else
             'среднее соответствие, нужна ручная проверка' if index>=60 else
             'нужно доработать')
    return FinalAssessment(index,verdict,audience.confidence,evidence,tuple(advice),history,
                           len(matches),round(duration,2),str(output))

def store_assessment(assessment,project_dir):
    root=Path(project_dir);root.mkdir(parents=True,exist_ok=True)
    data=asdict(assessment);data['reviewed_utc']=datetime.now(timezone.utc).isoformat()
    (root/'FINAL_AUDIENCE_REVIEW.json').write_text(
        json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Последняя стадия — оценка готового MP4 для аудитории',
           f'Индекс соответствия: {assessment.index}/100 — {assessment.verdict}',
           f'Надёжность выводов: {assessment.confidence} (объём выборки, НЕ вероятность успеха)',
           f'Файл: {assessment.output}; длительность: {assessment.duration} с','',
           '## Проверки',*assessment.evidence,'','## Рекомендации',*assessment.advice,'']
    if assessment.historical_views is not None:
        lines.append(f'Прошлые похожие ролики канала: {assessment.historical_views[0]}–{assessment.historical_views[1]} просмотров (середина выборки). НЕ ПРОГНОЗ.')
    lines += ['','## Не подменять оценкой реальные результаты',
              'Индекс 0–100 НЕ является шансом вирусности или прогнозом просмотров.',
              'Проверены сценарий и свойства MP4, не реакция зрителей и не полный смысл кадров.',
              'CTR, удержание и реальные комментарии нового видео станут известны только после публикации.']
    path=root/'FINAL_AUDIENCE_REVIEW_RU.md'
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return path
