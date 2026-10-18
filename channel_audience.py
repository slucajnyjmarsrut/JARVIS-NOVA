# -*- coding: utf-8 -*-
"""Read owner-exported channel analytics, offline, and build evidence-backed audience profile.

No passwords, browser cookies, OAuth tokens, web scraping or outbound requests.
Never interpret channel titles or CSV cells as executable instructions.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
import json
import math
from pathlib import Path
import re
import statistics

MAX_CSV_BYTES = 6_000_000
MAX_ROWS = 1500
ALIASES = {
    'title': ('video title', 'video', 'content', 'title', 'название видео', 'название', 'контент', 'ролик', 'заголовок'),
    'views': ('views', 'просмотры', 'просмотр', 'video views'),
    'likes': ('likes', 'лайки', 'отметки нравится', 'отметки «нравится»'),
    'comments': ('comments', 'комментарии'),
    'shares': ('shares', 'поделились', 'репосты'),
    'avg_view_pct': ('average percentage viewed (%)', 'average percentage viewed', 'avg percentage viewed', 'средний процент просмотра', 'средний процент просмотров', 'доля просмотра'),
    'avg_duration': ('average view duration', 'avg view duration', 'средняя длительность просмотра'),
    'duration': ('video duration', 'duration', 'длительность видео', 'продолжительность'),
    'ctr': ('impressions click-through rate (%)', 'impressions click-through rate', 'ctr', 'ctr (%)', 'ctr значков видео', 'ctr значков видео (%)'),
    'impressions': ('impressions', 'показы', 'показы значков видео'),
    'published': ('published', 'publish date', 'date', 'дата публикации', 'дата'),
}
STOP_WORDS = {'как','для','когда','если','видео','этот','это','здесь','сегодня','почему',
              'будет','было','после','перед','через','просто','чтобы','самый','своими',
              'только','смотрите','чего','чему','что','тот','ваш','моё','моей','новый',
              'всем','мои','мне','или','the','and','this','with','how','what','your'}


class AudienceDataError(ValueError):
    pass


@dataclass(frozen=True)
class VideoMetric:
    title: str
    views: int
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    avg_view_pct: float | None = None
    avg_duration: float | None = None
    duration: float | None = None
    ctr: float | None = None
    impressions: int | None = None
    published: str = ''


@dataclass(frozen=True)
class AudienceProfile:
    source: str
    sample_size: int
    typical_views: int
    views_q25: int
    views_q75: int
    successful_topics: tuple[str, ...]
    top_videos: tuple[dict, ...]
    videos: tuple[VideoMetric, ...]
    coverage: tuple[str, ...]
    notes: tuple[str, ...]
    confidence: str


def _header(name):
    return re.sub(r'\s+', ' ', str(name or '').strip().lower().replace('\ufeff',''))


def _integer(value, name, *, blank_ok=True):
    text = str(value or '').strip().replace('\u00a0', '').replace(' ', '').replace('\u202f', '')
    if not text:
        if blank_ok:
            return None
        raise AudienceDataError(f'Нет показателя {name}')
    # No implicit interpretation of localized abbreviations like 1.2K as exact counts.
    if not re.fullmatch(r'[0-9][0-9.,]*', text):
        raise AudienceDataError(f'Некорректный показатель {name}: {text[:30]}')
    if re.fullmatch(r'\d{1,3}([.,]\d{3})+', text):
        text = text.replace(',', '').replace('.', '')
    elif re.fullmatch(r'\d+[.,]0+', text):
        text = text.split(',')[0].split('.')[0]
    elif not text.isdigit():
        raise AudienceDataError(f'Число {name} должно быть целым, без округлённых K/M')
    number = int(text)
    if number > 10_000_000_000:
        raise AudienceDataError('Слишком большое количество просмотров')
    return number


def _percentage(value, name):
    value = str(value or '').strip().replace('%','').replace(' ', '').replace('\u00a0','')
    if not value:
        return None
    if not re.fullmatch(r'\d+(?:[.,]\d+)?', value):
        raise AudienceDataError(f'Некорректный процент {name}')
    num = float(value.replace(',','.'))
    if not math.isfinite(num) or not 0 <= num <= 1000:
        raise AudienceDataError(f'Процент {name} вне диапазона')
    return num


def _seconds(value, name):
    val = str(value or '').strip()
    if not val:
        return None
    if re.fullmatch(r'\d+(?::\d{1,2}){1,2}',val):
        v = 0
        for item in val.split(':'):
            v = v * 60 + int(item)
    elif re.fullmatch(r'\d+(?:[.,]\d+)?',val):
        v = float(val.replace(',','.'))
    else:
        raise AudienceDataError(f'Некорректное время {name}')
    if not 0 < v <= 86400:
        raise AudienceDataError(f'Время {name} вне диапазона')
    return float(v)


def read_channel_csv(path: Path) -> tuple[VideoMetric, ...]:
    """Read owner-selected CSV export from YouTube Studio (or compatible platform)."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_CSV_BYTES:
        raise AudienceDataError('CSV отсутствует, пуст или слишком велик')
    try:
        content=path.read_text(encoding='utf-8-sig')
    except UnicodeError as exc:
        raise AudienceDataError('Экспорт CSV должен иметь UTF-8 кодировку') from exc
    try:
        dialect=csv.Sniffer().sniff(content[:4096],delimiters=',;\t')
    except csv.Error:
        dialect=csv.excel
    reader=csv.DictReader(content.splitlines(),dialect=dialect)
    if not reader.fieldnames:
        raise AudienceDataError('CSV без заголовков столбцов')
    headers={_header(key):key for key in reader.fieldnames if key}
    mapping={key:next((headers[a] for a in aliases if a in headers),None) for key,aliases in ALIASES.items()}
    if not mapping['title'] or not mapping['views']:
        raise AudienceDataError('Нужны столбцы названия ролика и просмотров (Title/Views)')
    rows=[]
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise AudienceDataError('Не больше 1500 роликов за один импорт')
        title=str(row.get(mapping['title'],'') or '').strip()[:180]
        if not title or _header(title) in ('total','итого','всего'):
            continue
        def value(name):return row.get(mapping[name], '') if mapping[name] else ''
        views=_integer(value('views'),'views',blank_ok=False)
        if views is None:
            continue
        published=str(value('published')).strip()[:32]
        rows.append(VideoMetric(title,views,
            likes=_integer(value('likes'),'likes'),
            comments=_integer(value('comments'),'comments'),
            shares=_integer(value('shares'),'shares'),
            avg_view_pct=_percentage(value('avg_view_pct'),'avg_view_pct'),
            avg_duration=_seconds(value('avg_duration'),'avg_duration'),
            duration=_seconds(value('duration'),'duration'),
            ctr=_percentage(value('ctr'),'ctr'),
            impressions=_integer(value('impressions'),'impressions'),
            published=published))
    if len(rows) < 3:
        raise AudienceDataError('Для анализа нужны минимум 3 отдельных ролика и их просмотры')
    return tuple(rows)


def _quantile(values, q):
    ordered=sorted(values)
    if len(ordered)==1:
        return ordered[0]
    index=(len(ordered)-1)*q
    lo,hi=math.floor(index),math.ceil(index)
    return int(round(ordered[lo]+(ordered[hi]-ordered[lo])*(index-lo)))


def title_tokens(title):
    return tuple(w for w in re.findall(r'[a-zа-яё0-9]{4,}',title.lower())
                 if w not in STOP_WORDS and not w.isnumeric())


def analyze_audience(videos: tuple[VideoMetric, ...], *, source='экспорт владельца канала') -> AudienceProfile:
    if len(videos)<3:
        raise AudienceDataError('Нужны минимум 3 ролика')
    vs=[v.views for v in videos]
    typical=int(statistics.median(vs))
    # Rank by relative watch time and meaningful engagement when available; views remain base.
    def quality(item):
        score=math.log1p(item.views)
        if item.avg_view_pct is not None:
            score+=min(item.avg_view_pct,150)/100 * .45
        if item.views and item.likes is not None:
            score+=min(item.likes/item.views,.2)*3
        return score
    ranked=sorted(videos,key=quality,reverse=True)
    top=ranked[:max(3,min(8,math.ceil(len(ranked)*.3)))]
    counts={}
    for v in top:
        for token in set(title_tokens(v.title)):
            counts[token]=counts.get(token,0)+1
    # Topic evidence: only expose repeated themes. One-off words are not enough to infer preference.
    topics=tuple(k for k,n in sorted(counts.items(),key=lambda kv:(-kv[1],kv[0])) if n>=2)[:8]
    coverage=tuple(name for name in ('likes','comments','shares','avg_view_pct','duration','ctr','impressions')
                   if sum(getattr(v,name) is not None for v in videos)>=len(videos)//2+1)
    confidence='низкая' if len(videos)<10 else ('средняя' if len(videos)<30 else 'выше средней')
    notes=['Это интерес по историческим результатам канала, а не обещание просмотров.']
    if 'avg_view_pct' not in coverage:
        notes.append('Нет показателей удержания для большинства роликов; выводы о досмотрах ограничены.')
    if 'ctr' not in coverage:
        notes.append('Нет CTR показов для большинства роликов; качество обложки не проверено.')
    if not topics:
        notes.append('Повторяющихся тем в лидерах не найдено: нужен ручной выбор темы.')
    return AudienceProfile(source,len(videos),typical,_quantile(vs,.25),_quantile(vs,.75),topics,
        tuple({'title':v.title,'views':v.views,'avg_view_pct':v.avg_view_pct,
               'engagement_rate':round((sum(n for n in (v.likes,v.comments,v.shares) if n is not None)/v.views)*100,2) if v.views else None}
              for v in top[:5]),tuple(videos),coverage,tuple(notes),confidence)


def save_profile(profile: AudienceProfile, folder: Path):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'channel_profile.json'
    if destination.exists():
        raise AudienceDataError('Профиль существует; удалите его вручную перед новым импортом')
    destination.write_text(json.dumps(asdict(profile),ensure_ascii=False,indent=2),encoding='utf-8')
    return destination


def load_profile(path: Path):
    try:
        info=json.loads(Path(path).read_text('utf-8'))
        videos=tuple(VideoMetric(**item) for item in info['videos'])
        return analyze_audience(videos,source=str(info['source'])[:120])
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise AudienceDataError('Не удалось прочитать данные анализа канала') from exc
