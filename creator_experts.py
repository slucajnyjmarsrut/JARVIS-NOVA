# -*- coding: utf-8 -*-
"""Small, auditable specialist advisers driven by REAL channel data.

These are task-specific algorithms and prompts, not an invented team of humans.
Each adviser cites its evidence and flags gaps rather than hallucinating trends.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
from channel_audience import AudienceProfile, title_tokens

@dataclass(frozen=True)
class ExpertNote:
    specialist: str
    conclusion: str
    evidence: str
    action: str


def recommend_topic(profile: AudienceProfile) -> str:
    if not profile.successful_topics:
        raise ValueError('У канала нет устойчивой общей темы в лидирующих роликах; выберите её вручную')
    return ' / '.join(profile.successful_topics[:2])


def channel_experts(profile: AudienceProfile, topic: str) -> tuple[ExpertNote, ...]:
    if profile.sample_size < 3:
        raise ValueError('Недостаточно данных канала')
    subject=topic.strip()
    common=set(title_tokens(subject)) & set(profile.successful_topics)
    top=profile.top_videos[0]['title'] if profile.top_videos else ''
    alignment=(f'Есть совпадение с устойчивыми темами: {", ".join(sorted(common))}' if common else
               'Тема не подтверждена повторяющимися лидерами; гипотезу нужно проверить')
    return (
        ExpertNote('Аналитик аудитории',alignment,
            f'Анализировано {profile.sample_size} роликов; медиана {profile.typical_views} просмотров; '+
            f'достоверность: {profile.confidence}',
            'Опирайся на собственные результаты канала, не на общую популярность темы.'),
        ExpertNote('Редактор тем',f'Направление: {subject}',
            f'Повторяющиеся темы лидеров: {", ".join(profile.successful_topics) or "не обнаружены"}',
            'Выбери конкретную историю или практическую пользу, не повторяя чужие ролики.'),
        ExpertNote('Редактор зацепки','Покажи результат или конфликт в первые 2–3 секунды.',
            f'Пример успешного ролика канала: {top[:100]}',
            'Начни с конкретной демонстрации, убери вступление и приветствие.'),
        ExpertNote('Специалист по удержанию','Каждая следующая сцена должна отвечать на вопрос предыдущей.',
            'Исторические показатели удержания доступны' if 'avg_view_pct' in profile.coverage else
            'Показателей удержания в CSV недостаточно; рекомендация универсальна',
            'Запланируй смену крупности/смысла каждые 2–6 секунд и покажи результат до финала.'),
        ExpertNote('Редактор публикации','Подготовь честный заголовок, ясный текст на экране и явный CTA.',
            'CTR канала доступен' if 'ctr' in profile.coverage else
            'CTR отсутствует — эффект обложки оценить нельзя',
            'Не используй недоказанные сенсации, чужую музыку и ложные обещания.'),
    )


def prompt_context(profile: AudienceProfile, topic: str) -> str:
    """Small aggregated context sent ONLY to local Ollama; no raw channel CSV."""
    notes=channel_experts(profile,topic)
    package={
        'sample_size':profile.sample_size,'typical_views':profile.typical_views,
        'views_middle_half':[profile.views_q25,profile.views_q75],
        'recurring_topics':profile.successful_topics,
        'data_fields':profile.coverage,
        'confidence':profile.confidence,
        'expert_actions':[{'role':x.specialist,'action':x.action} for x in notes],
    }
    return json.dumps(package,ensure_ascii=False)


def expert_report(profile: AudienceProfile, topic: str) -> str:
    head=[f'# Анализ аудитории канала: {profile.sample_size} роликов',
          f'Медиана просмотров: {profile.typical_views}; середина наблюдений: {profile.views_q25}–{profile.views_q75}',
          f'Надёжность: {profile.confidence} (по объёму выборки, не вероятность успеха)',
          'Источники: экспорт статистики владельца; анализ полностью локальный.',
          '']
    for note in channel_experts(profile,topic):
        head.extend([f'## {note.specialist}',f'Вывод: {note.conclusion}',
                     f'Основание: {note.evidence}',f'Действие: {note.action}',''])
    head.extend(['Важно: исторические метрики не доказывают причинно-следственную связь.',*profile.notes])
    return '\n'.join(head)+'\n'
