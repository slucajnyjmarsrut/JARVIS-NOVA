# -*- coding: utf-8 -*-
"""Immediate, honest, topic-aware shooting briefs; no AI or network required.

The quick mode never spins up Ollama. This makes the first script responsive
on slow PCs while retaining selectable Qwen AI modes for deeper work.
"""
from __future__ import annotations

from viral_studio import Brief, Shot, validate_brief, _clean_text


def quick_brief(topic: str, research=(), *, audience=None) -> Brief:
    topic=_clean_text(topic,160,"Тема")
    t=topic.casefold().replace("ё","е")
    if any(word in t for word in ("гитар","караок","песн","вокал","музык")):
        title="Пой со мной: "+topic
        hook="Сможешь угадать песню по первым аккордам?"
        shots=(
            Shot(3,"Крупный план: пальцы берут узнаваемый аккорд на гитаре; "
                   "покажи инструмент и реакцию зрителя.", "УГАДАЕШЬ ПЕСНЮ?"),
            Shot(4,"Сними выбор песни: человек выбирает из двух названий "
                   "и быстро показывает свой вариант.", "КАКУЮ СЫГРАТЬ?"),
            Shot(6,"Запиши совместный припев или инструментальный фрагмент "
                   "со сменой крупного и общего плана.", "ПОЁМ ВМЕСТЕ"),
            Shot(5,"Поймай живую реакцию и улыбку участников. "
                   "Покажи яркий момент без длинного вступления.", "ЭТОТ МОМЕНТ!"),
            Shot(3,"Сделай финальный общий план и попроси предложить "
                   "следующую песню в комментариях.", "ЧТО СПЕТЬ ДАЛЬШЕ?"))
        script=("Открой ролик гитарным аккордом и вопросом «Угадаешь песню?». "
                "Покажи, какую композицию выбирает участник. "
                "Сними короткий совместный фрагмент, затем самую эмоциональную "
                "реакцию. В конце попроси зрителей предложить следующую песню.")
        cta="Какую песню сыграть следующей? Напиши в комментариях."
    elif any(word in t for word in ("роблокс","roblox","minecraft","майнкрафт","игр","стрим")):
        title="Один неожиданный момент: "+topic
        hook="Смотри, что случилось в этой игре!"
        shots=(
            Shot(3,"Покажи самый необычный игровой момент сразу, "
                   "без заставки.", "НЕОЖИДАННО!"),
            Shot(4,"Вернись на несколько секунд назад и объясни, "
                   "какое было задание или цель.", "КАК ВСЁ НАЧАЛОСЬ"),
            Shot(6,"Сними главное действие: 2–3 коротких ракурса "
                   "с акцентом на движение.", "ПОПЫТКА"),
            Shot(5,"Покажи результат, сравнив ожидание и реальность.", "ВОТ РЕЗУЛЬТАТ"),
            Shot(3,"Оставь вопрос зрителям о следующем испытании.", "ЧТО ПРОВЕРИТЬ?"))
        script=("Начни с неожиданного фрагмента игры. Объясни задачу одним "
                "предложением, покажи попытку и результат. Закончи вопросом "
                "о следующем челлендже.")
        cta="Какое испытание снять дальше?"
    elif any(word in t for word in ("рецепт","готов","кухн","еда","пицц","кофе")):
        title="Готовим быстро: "+topic
        hook="Вот результат, а теперь покажу, как его получить!"
        shots=(
            Shot(3,"Покажи готовое блюдо крупным планом.", "РЕЗУЛЬТАТ СРАЗУ"),
            Shot(4,"Разложи ингредиенты сверху и кратко покажи "
                   "их количество.", "ЧТО ПОНАДОБИТСЯ"),
            Shot(7,"Сними три ключевых действия процесса без пауз.", "ШАГ ЗА ШАГОМ"),
            Shot(5,"Покажи подачу, текстуру и финальный результат.", "ГОТОВО!"),
            Shot(3,"Попроси оценить рецепт или предложить вариацию.", "ОЦЕНИ РЕЦЕПТ"))
        script=("Начни с аппетитного результата, покажи ингредиенты, "
                "основные действия и финальную подачу. "
                "Не обещай точное время готовки без проверки.")
        cta="Какую вариацию этого рецепта приготовить?"
    else:
        title="Короткий эксперимент: "+topic
        hook="Что получится, если попробовать «"+topic+"»?"
        shots=(
            Shot(3,"Покажи главный результат или необычную деталь, "
                   "относящуюся к теме.", "СМОТРИ СЮДА"),
            Shot(4,"Сними исходную ситуацию и объясни цель в одном предложении.", "ЦЕЛЬ"),
            Shot(6,"Покажи два–три ключевых действия, напрямую "
                   "связанных с темой: "+topic+".", "ПРОЦЕСС"),
            Shot(5,"Сравни результат с исходным состоянием и покажи "
                   "подтверждённые наблюдения.", "ДО / ПОСЛЕ"),
            Shot(3,"Спроси зрителя, что показать или попробовать дальше.", "ТВОЙ ВАРИАНТ?"))
        script=("Открой видео результатом по теме «"+topic+"». "
                "Сразу объясни цель, затем продемонстрируй процесс и "
                "реальный итог. Заверши вопросом к зрителям.")
        cta="А какой вариант по этой теме ты бы попробовал?"
    return validate_brief(Brief(
        title=title,topic=topic,hook=hook,script=script,shots=shots,
        call_to_action=cta,generator="быстрый локальный сценарий (без нейросети)",
        research=tuple(research)[:10]))


def select_brief(topic, trends=(), *, mode="fast", audience=None, runtime=None,
                 ai_generator=None):
    """(brief, user-visible note). Fast never touches AI or network.

    AI errors are handled honestly: a fully local, topic-aware fallback is
    returned rather than a blank result or a misleading "AI succeeded".
    """
    if mode not in ("fast", "standard", "deep"):
        raise ValueError("Неизвестная скорость сценария")
    if mode=="fast":
        return quick_brief(topic,trends,audience=audience), (
            "⚡ Быстрый сценарий без ожидания ИИ. "
            "Это авторский локальный шаблон по теме, не результат Qwen."
        )
    if ai_generator is None:
        from viral_studio import create_local_brief
        ai_generator=create_local_brief
    kwargs={"audience":audience,
            "timeout_seconds":20 if mode=="standard" else 75,
            "max_tokens":850 if mode=="standard" else 1450}
    if runtime is not None:
        kwargs["model_runtime"]=runtime
        kwargs["stop_runtime"]=False
    try:
        return ai_generator(topic,trends,**kwargs), (
            "Сценарий подготовлен локальной Qwen."
        )
    except Exception as exc:
        return quick_brief(topic,trends,audience=audience), (
            "Qwen не завершила сценарий: "+str(exc)[:150]+
            ". Подготовлен быстрый локальный сценарий БЕЗ нейросети."
        )
