# -*- coding: utf-8 -*-
"""Local-only analytics for the owner's CSV. No passwords, OAuth, scraping or uploads."""
import csv
import json
import math
from collections import Counter
from dataclasses import dataclass,asdict
from pathlib import Path
import re
from statistics import median

class AudienceDataError(ValueError):pass

ALIASES={
 'title':('video title','title','content','название видео','название','заголовок'),
 'views':('views','video views','просмотры'),
 'likes':('likes','лайки','отметки «нравится»'),
 'comments':('comments','комментарии'),
 'shares':('shares','поделились','репосты'),
 'retention':('average percentage viewed','average percentage viewed (%)','средний процент просмотра'),
 'ctr':('impressions click-through rate','impressions click-through rate (%)','ctr','ctr (%)'),
 'duration':('duration','video duration','длительность видео'),
}
STOP={'этого','через','только','который','ролик','видео','сегодня','своими','было','будет','новый',
      'после','перед','когда','почему','смотри','смотреть','как','для','the','with','from','your'}
def tokens(text):
    return {x for x in re.findall(r'[а-яёa-z0-9]{4,}',str(text).lower()) if x not in STOP and not x.isnumeric()}
def number(value,kind='integer'):
    value=str(value or '').strip().replace('\u00a0','').replace(' ','').replace('%','')
    if not value:return None
    if kind=='percent':
        try: v=float(value.replace(',','.'))
        except ValueError:raise AudienceDataError('Неверный процент')
        if not 0<=v<=1000:raise AudienceDataError('Процент вне диапазона')
        return v
    if re.fullmatch(r'\d{1,3}([,.]\d{3})+',value):value=value.replace(',','').replace('.','')
    if not value.isdigit():raise AudienceDataError('Счётчики нужны точные (без K/M)')
    n=int(value)
    if n>10**10:raise AudienceDataError('Счётчик слишком велик')
    return n

@dataclass(frozen=True)
class Video:
    title:str
    views:int
    likes:int|None=None
    comments:int|None=None
    shares:int|None=None
    retention:float|None=None
    ctr:float|None=None
    duration:str=''
@dataclass(frozen=True)
class Audience:
    videos:tuple[Video,...]
    typical_views:int
    views_low:int
    views_high:int
    winning_topics:tuple[str,...]
    leaders:tuple[dict,...]
    confidence:str
    coverage:tuple[str,...]
    notes:tuple[str,...]

def import_csv(path):
    path=Path(path)
    if not path.is_file() or not 0<path.stat().st_size<=6_000_000:
        raise AudienceDataError('Нет CSV или CSV слишком большой')
    try:raw=path.read_text('utf-8-sig')
    except UnicodeError:raise AudienceDataError('Нужен UTF-8 CSV')
    try:dialect=csv.Sniffer().sniff(raw[:4096],delimiters=',;\t')
    except csv.Error:dialect=csv.excel
    reader=csv.DictReader(raw.splitlines(),dialect=dialect)
    headers={str(x).strip().lower():x for x in reader.fieldnames or [] if x}
    cols={field:next((headers[a] for a in aliases if a in headers),None) for field,aliases in ALIASES.items()}
    if not cols['title'] or not cols['views']:
        raise AudienceDataError('Нужны названия видео и просмотры: Title, Views')
    videos=[]
    for row in reader:
        if len(videos)>=1500:raise AudienceDataError('Не более 1500 строк')
        def get(key):return row.get(cols[key],'') if cols[key] else ''
        title=str(get('title') or '').strip()[:180]
        if not title or title.casefold() in ('total','итого','всего'):continue
        views=number(get('views'))
        if views is None:continue
        videos.append(Video(title,views,number(get('likes')),number(get('comments')),
                            number(get('shares')),number(get('retention'),'percent'),
                            number(get('ctr'),'percent'),str(get('duration'))[:25]))
    if len(videos)<3:raise AudienceDataError('Нужны минимум три опубликованных ролика')
    return tuple(videos)

def analyze(videos):
    videos=tuple(videos)
    if len(videos)<3:raise AudienceDataError('Нужны реальные данные хотя бы трёх роликов')
    values=sorted(v.views for v in videos)
    ranked=sorted(videos,key=lambda v:(math.log1p(v.views)+
                  .3*(min(v.retention,150)/100 if v.retention is not None else 0)+
                  3*(min(v.likes/v.views,.2) if v.likes is not None and v.views else 0)),reverse=True)
    leaders=ranked[:max(3,min(8,math.ceil(len(ranked)*.3)))]
    words=Counter(w for v in leaders for w in tokens(v.title))
    repeat=tuple(w for w,c in sorted(words.items(),key=lambda p:(-p[1],p[0])) if c>=2)[:8]
    cover=tuple(k for k in ('likes','comments','shares','retention','ctr')
                if sum(getattr(v,k) is not None for v in videos)>len(videos)/2)
    notes=['Выводы основаны только на экспортированной статистике своего канала.']
    if 'retention' not in cover:notes.append('Нет показателя досмотра у большинства роликов.')
    if 'ctr' not in cover:notes.append('CTR показов не подтверждён экспортом.')
    if not repeat:notes.append('Повторяющиеся темы лидеров не найдены; тему выбирает пользователь.')
    return Audience(videos,int(median(values)),values[(len(values)-1)//4],values[(len(values)*3)//4],
                    repeat,tuple({'title':v.title,'views':v.views,'retention':v.retention} for v in leaders[:5]),
                    'низкая' if len(videos)<10 else ('средняя' if len(videos)<30 else 'выше средней'),
                    cover,tuple(notes))

def audience_context(audience):
    """Summary only, passed to LOCAL LLM; neither full CSV nor token."""
    return json.dumps({'videos':len(audience.videos),'median_views':audience.typical_views,
                       'past_views_middle':[audience.views_low,audience.views_high],
                       'repeated_winning_topics':audience.winning_topics,
                       'available_metrics':audience.coverage,'confidence':audience.confidence},
                      ensure_ascii=False)

def recommend_topic(audience):
    if not audience.winning_topics:
        raise AudienceDataError('Не найден повторяющийся интерес; укажи тему вручную')
    return ' / '.join(audience.winning_topics[:2])

def report(audience):
    lines=['# Аудитория канала','Видео в выборке: '+str(len(audience.videos)),
           f'Типичные просмотры: {audience.typical_views}; диапазон середины прошлых результатов: {audience.views_low}–{audience.views_high}',
           'Повторяющиеся темы среди лидеров: '+(', '.join(audience.winning_topics) or 'нет'),
           'Достоверность по объёму выборки: '+audience.confidence,
           '## Лидеры канала']
    lines.extend(f'- {v["title"]}: {v["views"]} просмотров' for v in audience.leaders)
    lines.extend(['','## Ограничения',*(f'- {n}' for n in audience.notes),
                  '- Поиск трендов не заменяет анализа вашего канала.',
                  '- Оценка канала не является прогнозом просмотров.'])
    return '\n'.join(lines)+'\n'
