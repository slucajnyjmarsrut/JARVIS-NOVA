# -*- coding: utf-8 -*-
"""Expert-like specialised review stages; each verdict links to actual channel evidence.

No fictitious human expert or trained prediction model is claimed here.
"""
from dataclasses import dataclass
from channel_audience import audience_context, tokens

@dataclass(frozen=True)
class ExpertOpinion:
    role:str
    finding:str
    evidence:str
    instruction:str

def consult_experts(audience,topic):
    if not audience or len(audience.videos)<3:
        raise ValueError('Сначала получи показатели канала')
    overlaps=set(audience.winning_topics)&tokens(topic)
    return (
        ExpertOpinion('Аналитик аудитории',
                      'Подтверждена тема' if overlaps else 'Интерес не подтверждён — тестовая гипотеза',
                      f'{len(audience.videos)} прошлых видео; медиана {audience.typical_views} просмотров',
                      'Сценарий должен учитывать победившие темы канала.'),
        ExpertOpinion('Редактор тем','Тема: '+topic,
                      'Повторяющиеся темы лидеров: '+(', '.join(audience.winning_topics) or 'не найдены'),
                      'Дай конкретный неожиданный результат или практическую пользу.'),
        ExpertOpinion('Эксперт первых трёх секунд','Начни с результата или конфликта',
                      'Вывод о структуре, а не факт из статистики',
                      'Убери приветствие. Покажи интригу в первые 2–3 секунды.'),
        ExpertOpinion('Эксперт удержания','Не допускай пустых сцен',
                      'Статистика удержания: '+('есть' if 'retention' in audience.coverage else 'нет'),
                      'Меняй смысл кадра каждые 2–6 секунд. Покажи результат до финала.'),
        ExpertOpinion('Редактор публикации','Честный заголовок и CTA',
                      'CTR канала: '+('есть' if 'ctr' in audience.coverage else 'нет'),
                      'Не используй обманные обещания, нелицензированную музыку и чужой контент.')
    )

def expert_context(audience,topic):
    opinions=consult_experts(audience,topic)
    return audience_context(audience)+'\n'+'\n'.join(x.role+': '+x.instruction for x in opinions)

def expert_report(audience,topic):
    text=['# Специализированные редакторы JARVIS (это модули, не люди)']
    for opinion in consult_experts(audience,topic):
        text.extend(['',f'## {opinion.role}',opinion.finding,
                     'Данные: '+opinion.evidence,'Что делать: '+opinion.instruction])
    text.extend(['','Нет гарантий просмотров или попадания в рекомендации.'])
    return '\n'.join(text)+'\n'
