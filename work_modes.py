# -*- coding: utf-8 -*-
"""Auditable, deterministic JARVIS profiles for gaming, work, office and study.

A mode is not a new unrestricted AI agent. It only changes the vocabulary and
chooses a preset of exact Start-menu application names. No shell commands,
filesystem execution, blind clicks, closing apps or elevated actions.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

from agent_core import Plan, Step, normalize, strip_wake, validate_plan
from self_improve import default_data_file, safe_name


@dataclass(frozen=True)
class ModeSpec:
    label: str
    variants: tuple[str, ...]
    defaults: tuple[str, ...]
    shortcuts: tuple[tuple[str, tuple[str, ...], str], ...]
    introduction: str


MODES: dict[str, ModeSpec] = {
    'gaming': ModeSpec('Игры', ('игровой', 'игры', 'игровой режим', 'гейминг'),
        ('Steam', 'Discord'),
        (('лаунчер', ('открой лаунчер', 'запусти лаунчер'), 'Steam'),
         ('общение', ('открой связь', 'открой дискорд'), 'Discord')),
        'Игровой режим: запуск Steam и Discord, управление громкостью и пауза вручную.'),
    'work': ModeSpec('Работа', ('рабочий', 'работа', 'рабочий режим'),
        ('Google Chrome', 'Notepad'),
        (('заметки', ('открой заметки', 'запусти заметки'), 'Notepad'),
         ('браузер', ('открой рабочий браузер',), 'Google Chrome')),
        'Рабочий режим: браузер, заметки и фокус-таймер.'),
    'office': ModeSpec('Офис', ('офис', 'офисный', 'офисный режим'),
        ('Explorer', 'Notepad', 'Calculator'),
        (('документ', ('создай документ', 'открой документ'), 'Notepad'),
         ('файлы', ('открой рабочие файлы', 'открой папки'), 'Explorer'),
         ('подсчёты', ('открой вычисления', 'открой калькулятор'), 'Calculator')),
        'Офисный режим: проводник, документы и калькулятор.'),
    'study': ModeSpec('Учёба', ('учебный', 'учеба', 'учёба', 'учебный режим'),
        ('Notepad', 'Calculator'),
        (('конспект', ('открой конспект', 'создай конспект'), 'Notepad'),
         ('практика', ('открой задачи', 'открой калькулятор'), 'Calculator')),
        'Учебный режим: конспект, практика и 25-минутные учебные блоки.'),
}

_MODE_ALIASES={normalize(alias):mode for mode,spec in MODES.items() for alias in spec.variants}
_NEUTRAL={'нейтральный режим','обычный режим','выключи режим',
          'выйди из режима','отключи режим','режим по умолчанию'}
_START={'начни сессию','начать сессию','запусти набор','запусти приложения',
        'открой приложения','старт режима','начни режим'}
_MODE_START={'gaming':{'игровой старт','начни игровой сеанс','начни игру'},
             'work':{'рабочий старт','начни работу'},
             'office':{'офисный старт','начни офисный день'},
             'study':{'учебный старт','начни учебу','начни учёбу','начни занятие'}}
_HELP={'что умеешь в этом режиме','команды режима','подскажи команды режима',
       'помощь по режиму','какой режим включен','какой режим включён'}
_STOP_TIMER={'останови таймер','отмени таймер','сбрось таймер','выключи таймер'}
_TIMER_STATUS={'сколько осталось','сколько осталось на таймере','статус таймера'}
_TIMER = re.compile(r'^(?:поставь\s+)?(?:таймер|фокус|фокус таймер)\s+(?:на\s+)?(\d{1,3})\s*(?:минуты?|мин)?$')


@dataclass
class ModeCommand:
    kind: str
    message: str = ''
    mode: str = ''
    plan: Plan | None = None
    minutes: int = 0


def _switch_target(text: str) -> str | None:
    if text in _NEUTRAL:
        return 'neutral'
    for pattern in (r'^(?:включи|активируй|выбери|переключись на|перейди в)\s+(.+?)(?:\s+режим)?$',
                    r'^режим\s+(.+)$', r'^(.+?)\s+режим$'):
        match=re.fullmatch(pattern,text)
        if match:
            target=match.group(1).strip()
            if target in ('обычный','нейтральный'):
                return 'neutral'
            if target in _MODE_ALIASES:
                return _MODE_ALIASES[target]
    return None


class ModeManager:
    """No arbitrary instructions from voice, network or edited config files."""

    def __init__(self, path: Path | None = None):
        self.mode='neutral'  # ephemeral session state, does not leak into next launch
        self.path=Path(path) if path is not None else default_data_file().with_name('modes-v1.json')
        self.overrides: dict[str,tuple[str,...]]={}
        self._load()

    def _load(self):
        try:
            if not self.path.is_file() or self.path.stat().st_size>8192:
                return
            doc=json.loads(self.path.read_text('utf-8'))
            if not isinstance(doc,dict) or doc.get('version')!=1:
                return
            apps=doc.get('apps',{})
            if not isinstance(apps,dict):return
            for key,items in apps.items():
                if key in MODES and type(items) is list and 1<=len(items)<=3 and all(safe_name(v) for v in items):
                    self.overrides[key]=tuple(items)
        except (OSError, ValueError, UnicodeError, TypeError):
            pass

    def configure(self,mode:str,programs:list[str],is_installed:Callable[[str],bool]):
        if mode not in MODES:raise ValueError('Неизвестный режим')
        if not 1<=len(programs)<=3:raise ValueError('Выбери от одной до трёх программ')
        cleaned=tuple(s.strip() for s in programs)
        if len({normalize(p) for p in cleaned})!=len(cleaned):
            raise ValueError('Программа повторяется')
        if any(not safe_name(s) for s in cleaned):
            raise ValueError('Разрешены только безопасные названия программ, не пути и команды')
        if any(not is_installed(s) for s in cleaned):
            raise ValueError('Программа не найдена в меню Пуск. Нужны точные установленные названия.')
        candidate={**self.overrides,mode:cleaned}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.modes-',suffix='.tmp',dir=str(self.path.parent))
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as out:
                json.dump({'version':1,'apps':candidate},out,ensure_ascii=False,indent=2)
                out.flush();os.fsync(out.fileno())
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)
        self.overrides=candidate

    def apps(self,mode:str|None=None)->tuple[str,...]:
        key=mode or self.mode
        if key not in MODES:return ()
        return self.overrides.get(key,MODES[key].defaults)

    def help(self):
        if self.mode=='neutral':
            return ('Режимы: Игры, Работа, Офис, Учёба. Скажи «Джарвис, включи игровой режим» '
                    'или выбери режим в меню. Есть пакетный запуск приложений и фокус-таймер.')
        spec=MODES[self.mode]
        commands=', '.join(v[0] for v in spec.shortcuts)
        return (f'Режим «{spec.label}». {spec.introduction} '
                f'Команды: «начни сессию», {commands}, «таймер 25 минут», '
                '«сколько осталось», «останови таймер», «обычный режим».')

    def build_launch(self,mode:str,is_installed:Callable[[str],bool],apps:tuple[str,...]|None=None):
        desired=apps if apps is not None else self.apps(mode)
        ready=[];missing=[]
        for name in desired:
            if is_installed(name):ready.append(name)
            else:missing.append(name)
        if not ready:
            return ModeCommand('message','Для этого режима не найдены программы. Укажи установленные приложения через меню «Режимы».')
        # All preconfigured batch launches need confirmation even when individual opens don't.
        plan=validate_plan(Plan(steps=[Step('open_app',name) for name in ready],
                                need_confirmation=True,source='mode'))
        summary='Запущу по очереди: '+', '.join(ready)+'.'
        if missing:summary+=' Пропущены отсутствующие: '+', '.join(missing)+'.'
        return ModeCommand('launch',summary,mode,plan)

    def parse(self,spoken:str,is_installed:Callable[[str],bool])->ModeCommand|None:
        phrase=normalize(strip_wake(spoken))
        if not phrase:return None
        # A negated sentence must never be treated as a request to enable a mode.
        if re.match(r'^(?:не|не надо|пожалуйста не)\s+',phrase):return None
        target=_switch_target(phrase)
        if target:
            self.mode=target
            if target=='neutral':return ModeCommand('switch','Обычный режим. Без автоматического запуска программ.',target)
            return ModeCommand('switch',self.help(),target)
        if phrase in _HELP:
            return ModeCommand('message',self.help(),self.mode)
        if phrase in _STOP_TIMER:
            return ModeCommand('timer_stop','Останавливаю фокус-таймер.',self.mode)
        if phrase in _TIMER_STATUS:
            return ModeCommand('timer_status',mode=self.mode)
        if phrase in ('помодоро','начни помодоро','начни фокус'):
            if self.mode not in {'work','office','study'}:
                return ModeCommand('message','Фокус-таймер доступен в режимах Работа, Офис, Учёба.')
            return ModeCommand('timer_start','Фокус-таймер на 25 минут.',self.mode,minutes=25)
        mt=_TIMER.fullmatch(phrase)
        if mt:
            minutes=int(mt.group(1))
            if self.mode not in {'work','office','study'}:
                return ModeCommand('message','Фокус-таймер доступен в режимах Работа, Офис, Учёба.')
            if minutes<1 or minutes>120:
                return ModeCommand('message','Укажи от 1 до 120 минут.')
            return ModeCommand('timer_start',f'Фокус-таймер на {minutes} минут.',self.mode,minutes=minutes)
        if self.mode=='neutral':return None
        if phrase in _START or phrase in _MODE_START[self.mode]:
            return self.build_launch(self.mode,is_installed)
        for title,aliases,app in MODES[self.mode].shortcuts:
            if phrase in aliases:
                return self.build_launch(self.mode,is_installed,(app,))
        return None
