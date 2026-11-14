# -*- coding: utf-8 -*-
"""Chat-first routing for *explicit* JARVIS NOVA requests.

Pure data-only intent classification: no file writes, networking, model-suggested
tool names, or implicit permissions. Only existing audited controller actions
may be selected; ambiguous questions remain ordinary conversation.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from code_languages import ALIASES
from manual_file_deletion import is_delete_request, is_folder_request


@dataclass(frozen=True)
class ChatIntent:
    kind: str
    value: str = ""


def _normal(text: str) -> str:
    text = re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip()
    text = text.strip(" .,!?;:…")
    if text.startswith("я хочу "):
        text = text[2:]
    elif text.startswith("я бы хотел "):
        text = "хочу " + text[len("я бы хотел "):]
    return re.sub(
        r"^(?:(?:эй|слушай|окей|привет)[ ,]+)?"
        r"(?:джарвис|жарвис|джервис|гарвис)[ ,:!-]+",
        "", text, count=1).strip(" .,!?;:…")


def _language(text: str) -> str | None:
    # Exclude ambiguous one-letter words and unrelated 'go', 'r', 'си'.
    ignored = {"c", "си", "go", "го", "r", "lua"}
    languages = {
        language for alias, language in ALIASES.items()
        if alias not in ignored and
        re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text)
    }
    # A site is typically HTML, but the user can name another language.
    if len(languages) > 1:
        return ""  # Ask, never choose one at random.
    if languages:
        return next(iter(languages))
    return "html" if re.search(r"\b(?:сайт|веб.?страниц[ауые]?|лендинг)\b", text) else "python"


def route_chat_request(text: str) -> ChatIntent | None:
    """Return an allowlisted intent or None: no side effects at this stage."""
    if not isinstance(text, str) or not 1 <= len(text) <= 1200:
        return None
    s = _normal(text)
    # Deletion requests are handled before coding, models or OS commands.
    # This intent can ONLY reveal an item in Explorer via a user file picker.
    if is_delete_request(text):
        return ChatIntent("manual_delete","folder" if is_folder_request(text) else "file")
    # Asking how to begin is help, even when it begins with "не" or "как".
    # Do not weaken negation guards for any other command.
    if s in {"не понимаю что делать", "как начать", "как пользоваться",
             "с чего начать"}:
        return ChatIntent("help")
    if not s or re.match(
        r"^(?:не |я не |не надо |не нужно |если |допустим |"
        r"расскажи |объясни |как |почему |зачем |когда |"
        r"можно ли |возможно ли |что будет |а если )", s):
        return None
    # User-driven stepwise workflows: these only OPEN existing editors and
    # never execute generated code, alter files, or grant permissions.
    if s in {"по шагам", "работай по шагам", "составь план",
             "раздели задачу на части", "разбей задачу на шаги",
             "сделай план и проверяй каждый шаг"}:
        return ChatIntent("clarify_workflow")
    code_steps=re.fullmatch(
        r"(?:сделай|создай|напиши|подготовь) "
        r"(?:по шагам|по этапам|по частям) "
        r"((?:программу|приложение|код|сайт|бота|игру|скрипт|"
        r"проект|api) .{3,220})",s)
    if code_steps:
        return ChatIntent("code_steps",code_steps.group(1))
    code_steps=re.fullmatch(
        r"(?:сделай|создай|напиши|подготовь) "
        r"(?:программу|приложение|код|сайт|бота|игру|скрипт|проект) "
        r"(?:по шагам|по этапам|по частям)(?: (.{3,220}))?",s)
    if code_steps:
        return ChatIntent("code_steps",code_steps.group(1) or s)
    video_steps=re.fullmatch(
        r"(?:создай|сделай|подготовь) (?:видео|ролик|сценарий) "
        r"(?:по шагам|по этапам|по частям)"
        r"(?: (?:на тему|про|о) (.{2,160}))?",s)
    if video_steps:
        return ChatIntent("scenario_steps",video_steps.group(1) or "")
    # Brief, ambiguous requests require a question, not an arbitrary action.
    # No consent, downloads, screenshots or file writes from these phrases.
    if s in {"видео", "ролик", "видеомонтаж", "хочу видео", "хочу ролик"}:
        return ChatIntent("clarify_video")
    if s in {"модель", "модели", "qwen", "квен", "нейросеть"}:
        return ChatIntent("clarify_model")
    if s in {"экран", "зрение", "скриншот", "мой экран"}:
        return ChatIntent("clarify_screen")
    if s in {"код", "программа", "программирование", "хочу программу"}:
        return ChatIntent("clarify_code")
    if s in {
        "помоги", "начать", "с чего начать", "не понимаю что делать",
        "что здесь делать", "как начать", "помоги начать",
        "что ты умеешь", "что ты можешь", "что умеешь", "помощь", "помоги разобраться",
        "покажи команды", "список команд", "что можно написать",
    }:
        return ChatIntent("help")
    if s in {"открой настройки", "покажи настройки", "хочу открыть настройки",
             "хочу настроить джарвис", "настройки джарвис", "настройки"}:
        return ChatIntent("settings")
    if s in {"проверь обновления", "проверить обновления", "обнови джарвис",
             "хочу обновить джарвис", "покажи обновления", "есть ли обновления",
             "хочу проверить обновления"}:
        return ChatIntent("updates")
    if s in {
        "проверь все модели на пк", "проверь все модели на компьютере",
        "найди модели на всем пк", "найди модели на всем компьютере",
        "найди модели на всех дисках", "проверь модели на всех дисках",
        "сканируй компьютер на модели", "поищи установленные модели",
        "поищи скачанные модели", "найди нейросети на компьютере",
        "проверь весь пк на модели", "проверь компьютер на модели",
        "найди все локальные модели", "какие модели есть на пк",
        "найди модели", "найти модели", "поиск моделей",
    }:
        return ChatIntent("model_scan")
    if s in {
        "останови поиск моделей", "отмени поиск моделей",
        "прерви сканирование моделей", "останови сканирование моделей"
    }:
        return ChatIntent("cancel_model_scan")
    # Explicit install and inspection are separate consent-preserving actions.
    if s in {"скачай qwen", "скачать qwen", "установи qwen",
             "установить qwen", "скачай модель", "скачать модель",
             "скачай локальную модель", "скачать локальную модель",
             "установи локальную модель", "установить локальную модель",
             "хочу установить qwen"}:
        return ChatIntent("model_download")
    if s in {"проверь qwen", "проверить qwen",
             "проверь локальную модель", "проверить локальную модель"}:
        return ChatIntent("model")
    if s in {"останови скачивание qwen", "отмени загрузку qwen",
             "останови загрузку модели", "отмени скачивание модели"}:
        return ChatIntent("cancel_model")
    if s in {"разреши управлять компьютером", "хочу разрешить управление пк",
             "разреши управление пк"}:
        return ChatIntent("permission_control")
    # Explicit opt-in wording, including the natural sentence reported by a user.
    # A recognized phrase only opens the existing OS-level consent dialog;
    # text itself never sets vision_allowed or captures the desktop.
    if s in {"разреши видеть экран", "разреши чтение экрана",
             "хочу разрешить анализ экрана", "разреши экран",
             "разреши зрение", "разрешить зрение",
             "разрешить доступ к экрану", "разрешаю доступ к экрану",
             "разрешаю видеть экран", "разрешаю зрение",
             "разрешаю захват экрана", "включи зрение",
             "хочу дать доступ к экрану", "зрение разрешаю",
             "зрение и экран разрешаю", "экран и зрение разрешаю"}:
        return ChatIntent("permission_screen")
    if s in {"отзови все разрешения", "отключи доступ к компьютеру",
             "отключи все разрешения"}:
        return ChatIntent("revoke")
    if s in {"открой мини чат", "сверни джарвис", "спрячь главное окно"}:
        return ChatIntent("minimize")

    ai = re.fullmatch(
        r"(?:хочу использовать|включи|выбери|переключись на) "
        r"(qwen|квен|локальную qwen|freellm|фриллм|только команды)", s)
    if ai:
        names = {"qwen": "bundled", "квен": "bundled",
                 "локальную qwen": "bundled", "freellm": "freellm",
                 "фриллм": "freellm", "только команды": "none"}
        return ChatIntent("engine", names[ai.group(1)])

    if s in {"разобрать снимок", "разбери снимок",
             "разобрать скриншот", "посмотреть скриншот",
             "хочу показать скриншот", "хочу отправить скриншот",
             "открой разметку скриншота", "проверить скриншот",
             "хочу проверить скриншот"}:
        return ChatIntent("screenshot")
    if s in {"открой filmcraft", "хочу filmcraft", "запусти filmcraft"}:
        return ChatIntent("filmcraft")
    scenario = re.fullmatch(
        r"(?:хочу |мне нужно |пожалуйста )?"
        r"(?:сделать |создать |написать |придумать |подготовить )?"
        r"сценарий(?: для видео| для ролика| ролика)?"
        r"(?: (?:про|о|об|на тему) (.{2,100}))?", s)
    if scenario:
        return ChatIntent("scenario",scenario.group(1) or "")
    scenario = re.fullmatch(
        r"(?:создай|сделай|напиши|придумай|подготовь) "
        r"сценарий(?: для видео| для ролика| ролика)?"
        r"(?: (?:про|о|об|на тему) (.{2,100}))?",s)
    if scenario:
        return ChatIntent("scenario",scenario.group(1) or "")
    if s in {"создать видео", "создай видео", "сделать видео",
             "создать ролик", "хочу создавать видео",
             "открой видеостудию", "открой видео студию", "хочу видеостудию",
             "открой студию видео"}:
        return ChatIntent("studio")
    if s in {"хочу создать аккаунт youtube", "хочу зарегистрироваться в tiktok",
             "хочу создать аккаунт в инстаграм", "открой регистрацию аккаунтов"}:
        return ChatIntent("accounts")
    if (re.match(r"^(?:хочу |мне нужно |помоги )", s) and
        re.search(r"\b(?:опубликовать|выложить|публикацию)\b", s) and
        re.search(r"\b(?:видео|ролик|youtube|ютуб|тикток|tiktok)\b", s)) or s in {
            "открой подготовку публикации", "подготовь публикацию видео"}:
        return ChatIntent("publish")

    # Prefer the specialised multitrack editor to the generic timeline.
    if s in {"открой многодорожечный монтаж", "хочу многодорожечный монтаж",
             "открой редактор наложений"} or (
        re.match(r"^(?:хочу |мне нужно |помоги |добавь |наложи )", s) and
        re.search(r"(?:наложени|логотип|озвучк|музык.*на видео|"
                  r"картинк.*на видео|видео на видео)", s)):
        return ChatIntent("multitrack")
    if s in {"хочу эдит", "хочу сделать эдит", "сделай эдит",
             "хочу shorts", "хочу reels", "хочу tiktok монтаж",
             "открой редактор эдитов"}:
        return ChatIntent("edits")
    if (re.match(r"^(?:хочу |сделай |собери |смонтируй |сократи )",s)
            and re.search(r"\b15\s*(?:минут|мин)\b",s)
            and re.search(r"(?:длинн|двухчас|2\s*час|из .*видео|из .*клип|из .*запис)",s)):
        return ChatIntent("longform","900")
    if s in {"смонтировать", "смонтировать видео", "смонтировать ролик",
             "открой таймлайн", "открой видеоредактор",
             "хочу смонтировать видео", "хочу сделать монтаж",
             "хочу монтировать видео", "хочу монтаж видео",
             "хочу отредактировать видео", "хочу обрезать видео",
             "хочу смонтировать ролик", "хочу монтаж", "открой монтаж",
             "мне нужно смонтировать ролик", "начать монтаж"}:
        return ChatIntent("timeline")
    if s in {"хочу создать ролик", "хочу сделать ролик",
             "хочу создать видео", "хочу снять ролик",
             "хочу сделать видео", "хочу видео для ютуба"}:
        return ChatIntent("studio")

    if s in {"хочу поиграть", "хочу играть", "давай поиграем",
             "открой игровой режим"}:
        return ChatIntent("gaming")

    # A short task label opens the editor only: do not auto-generate an
    # unspecified project and never silently write files.
    if s in {"написать код", "напиши код", "программировать",
             "написать программу", "создать программу",
             "хочу написать код", "хочу писать программу"}:
        return ChatIntent("code_start")
    # Default language for an unspecified software project is Python.
    code_starts = (
        "хочу написать ", "хочу создать ", "хочу сделать ",
        "мне нужно написать ", "мне нужно создать ",
        "помоги написать ", "помоги создать ", "открой редактор кода",
        "открой программирование", "хочу программировать",
        "хочу писать код",
    )
    if s in {"открой программирование", "открой редактор кода",
             "хочу программировать", "хочу писать код"} or (
        s.startswith(code_starts) and re.search(
            r"\b(?:программ\w*|код\w*|сайт|лендинг|скрипт\w*|"
            r"приложени\w*|бот\w*|игру|игра|проект\w*|"
            r"плагин\w*|мод\w*|модел\w*|карт\w*|мир|сервер\w*|api)\b", s)):
        return ChatIntent("code", _language(s))

    # Allow natural 'I want to open X' for already vetted desktop planner.
    # The controller still calls parse_local+validate_plan, never a shell.
    match = re.fullmatch(
        r"(?:хочу |мне нужно |пожалуйста )?(?:открыть|запустить) (.{1,90})", s)
    if match:
        return ChatIntent("open_desktop", match.group(1))
    match = re.fullmatch(r"хочу (?:открыть|запустить) (.{1,90})", s)
    if match:
        return ChatIntent("open_desktop", match.group(1))
    return None
