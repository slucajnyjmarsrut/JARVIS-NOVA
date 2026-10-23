# -*- coding: utf-8 -*-
"""JARVIS NOVA Python agent: bounded plans, no arbitrary shell execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import json
import os
import re
import ipaddress
from urllib.parse import urlsplit
import urllib.request
from self_improve import BLOCKED, safe_name


@dataclass(frozen=True)
class Step:
    kind: str
    value: str = ""
    x: int = 0
    y: int = 0
    amount: int = 0

@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    answer: str = ""
    question: str = ""
    need_confirmation: bool = False
    source: str = "local"

# Executable names never come directly from a language-model-proposed path.
ALLOWED_KINDS = {"open_app", "open_url", "minimize", "maximize", "restore",
                 "zoom_in", "zoom_out", "volume_up", "volume_down", "mute",
                 "move", "click", "scroll", "type", "hotkey", "close_window",
                 "screen_describe", "window_status"}
RISKY = {"close_window", "click", "type", "hotkey", "move"}
AI_ALLOWED = {"open_app","minimize","maximize","restore","zoom_in","zoom_out",
              "volume_up","volume_down","window_status","screen_describe"}
# Keep voice/AI execution policy aligned with the confirmed-alias learning store.
# Otherwise e.g. "cmd.exe" and "pwsh" could bypass the small spoken denylist.
UNSAFE_APPS = BLOCKED
ALIASES = {"хром": "Google Chrome", "храм": "Google Chrome",
           "браузер": "Google Chrome", "гугл хром": "Google Chrome",
           "стим": "Steam", "дискорд": "Discord", "телеграм": "Telegram",
           "блокнот": "Notepad", "проводник": "Explorer", "калькулятор": "Calculator",
           "файрфокс": "Mozilla Firefox", "мозила": "Mozilla Firefox",
           "эдж": "Microsoft Edge", "майкрософт эдж": "Microsoft Edge",
           "пейнт": "Paint", "рисовалка": "Paint",
           "ворд": "Word", "майкрософт ворд": "Word",
           "эксель": "Excel", "майкрософт эксель": "Excel",
           "пауэрпоинт": "PowerPoint", "презентации": "PowerPoint",
           "влс": "VLC media player", "влц": "VLC media player",
           "обс": "OBS Studio", "обс студио": "OBS Studio",
           "спотифай": "Spotify", "зум": "Zoom",
           "визуал студио код": "Visual Studio Code",
           "вс код": "Visual Studio Code", "фотошоп": "Adobe Photoshop",
           "вотсап": "WhatsApp", "вацап": "WhatsApp"}
# Match explicit direct address at the START of speech, including natural pauses:
# "Эй, Джарвис", "Слушай — Джарвис", "Привет, Джарвис".
# Require a boundary after both words: mentions in the middle and "джарвисов"
# must never activate desktop commands. No fuzzy authorization here.
WAKE = re.compile(
    r"^\\s*(?:(?:эй|окей|слушай|ну|привет)\\b[\\s,.:;!?—–-]+)?"
    r"(?:джарвис|жарвис|джервис|гарвис)\\b[\\s,.:;!?—–-]*",
    re.I,
)
NEGATE = re.compile(r"\b(?:не\s+(?:открывай|закрывай|нажимай|пиши|трогай|запускай|сворачивай)|отмена)\b", re.I)

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().replace("ё", "е").strip(" \t\n.,!?"))

def strip_wake(text: str) -> str:
    return WAKE.sub("", text).strip()

def parse_local(text: str) -> Plan:
    s = normalize(strip_wake(text))
    if not s: return Plan(question="Что сделать?")
    if NEGATE.search(s): return Plan(answer="Хорошо, не выполняю.")
    compound = re.match(r"(?:открой|запусти|включи)\s+(.+?)\s+и\s+(?:увеличь|приблизь)\s+масштаб$",s)
    if compound:
        target=compound[1].strip()
        if not safe_name(ALIASES.get(target,target)):
            return Plan(question="Запуск системных оболочек и небезопасных программ не поддерживается.")
        return Plan(steps=[Step("open_app",ALIASES.get(target,target)),Step("zoom_in")])
    if s in {"стоп", "отмена", "прекрати"}: return Plan(answer="Остановлено.")
    if s in {"спасибо", "благодарю"}: return Plan(answer="Пожалуйста.")
    if re.search(r"(?:что ты видишь|посмотри на экран|опиши экран|что на экране)",s):
        return Plan(steps=[Step("screen_describe")])
    if re.search(r"(?:какое окно|где я сейчас|какая программа открыта)",s):
        return Plan(steps=[Step("window_status")])
    if re.search(r"(?:закрой|выключи)\s+(?:активное\s+)?окно",s):
        return Plan(steps=[Step("close_window")],need_confirmation=True)
    if re.search(r"(?:сверни|убери)\s+(?:текущее|активное|это)?\s*окно",s):
        return Plan(steps=[Step("minimize")])
    if re.search(r"(?:разверни|распахни)\s+(?:текущее|активное|это)?\s*окно",s):
        return Plan(steps=[Step("maximize")])
    if re.search(r"(?:верни|восстанови)\s+(?:текущее|активное|это)?\s*окно",s):
        return Plan(steps=[Step("restore")])
    if re.search(r"(?:увеличь|приблизь|повысь)\s+масштаб",s):
        return Plan(steps=[Step("zoom_in")])
    if re.search(r"(?:уменьши|отдали|понизь)\s+масштаб",s):
        return Plan(steps=[Step("zoom_out")])
    if re.search(r"(?:сделай громче|прибавь звук|увеличь громкость)",s):
        return Plan(steps=[Step("volume_up")])
    if re.search(r"(?:сделай тише|убавь звук|уменьши громкость)",s):
        return Plan(steps=[Step("volume_down")])
    if re.search(r"(?:без звука|выключи звук)",s):
        return Plan(steps=[Step("mute")])
    m = re.search(r"(?:напечатай|введи текст|напиши)\s+(.+)",s)
    if m:
        # Keep exact text from the original utterance after the command.
        raw = re.split(r"(?:напечатай|введи текст|напиши)\s+",strip_wake(text),maxsplit=1,flags=re.I)
        return Plan(steps=[Step("type",raw[-1])],need_confirmation=True)
    m = re.search(r"(?:нажми|кликни|щёлкни)\s+(?:мышью\s+)?(?:по\s+)?(?:точке\s+)?(\d{1,5})\s*(?:[,;]|\s)\s*(\d{1,5})\b",s)
    if m:
        return Plan(steps=[Step("click",x=int(m[1]),y=int(m[2]))],need_confirmation=True)
    m = re.search(r"(?:перемести|подвинь)\s+курсор\s+(?:на\s+)?(\d{1,5})\s*(?:[,;]|\s)\s*(\d{1,5})\b",s)
    if m:
        return Plan(steps=[Step("move",x=int(m[1]),y=int(m[2]))])
    m = re.search(r"(?:прокрути|листани)\s+(вверх|вниз)(?:\s+(\d+))?",s)
    if m:
        direction=1 if m[1]=="вверх" else -1
        return Plan(steps=[Step("scroll",amount=direction*min(10,int(m[2] or "3")))])
    m = re.search(r"(?:нажми\s+)(enter|tab|escape|esc|пробел|энтер|ввод)",s)
    if m:
        key={"энтер":"enter","ввод":"enter","пробел":"space","esc":"esc"}.get(m[1],m[1])
        return Plan(steps=[Step("hotkey",key)],need_confirmation=True)
    m = re.search(r"(?:открой|запусти|включи|покажи)\s+(?:мне\s+)?(.+)",s)
    if m:
        target = re.sub(r"\b(?:пожалуйста|сейчас|программу|приложение)\b","",m[1]).strip()
        pair=re.split(r"\s+и\s+(?:увеличь|приблизь)\s+масштаб",target,maxsplit=1)
        next_zoom = len(pair)==2
        target=pair[0].strip()
        # The normalized utterance is for matching commands ONLY. Preserve
        # the original URL path/query case: /SignIn?Token=ABC is not the
        # same address as /signin?token=abc on many services.
        if target.startswith(("http://","https://")):
            original=re.match(
                r"^\s*(?:открой|запусти|включи|покажи)\s+(?:мне\s+)?(https?://\S+)",
                strip_wake(text),flags=re.I)
            if original:
                raw_url=original.group(1)
                target=raw_url.split("://",1)[0].lower()+"://"+raw_url.split("://",1)[1]
        if not target: return Plan(question="Какое приложение открыть?")
        if target in UNSAFE_APPS:
            return Plan(question="Запуск системных оболочек не поддерживается.")
        if target.startswith(("http://","https://")):
            if not _safe_https_url(target):
                return Plan(question="Можно открыть только корректную внешнюю HTTPS-ссылку.")
            st=Step("open_url",target)
        else:
            application=ALIASES.get(target,target)
            if not safe_name(application):
                return Plan(question="Запуск этой системной оболочки или небезопасного пути не поддерживается.")
            st=Step("open_app",application)
        steps=[st]+([Step("zoom_in")] if next_zoom else [])
        return Plan(steps=steps)
    if s in {"открой", "запусти", "включи", "нажми"}:
        return Plan(question="Уточни, что именно нужно открыть или нажать.")
    return Plan(question="Не понял команду. Уточни действие или название программы.")

def _safe_https_url(address: str) -> bool:
    """Validate an external HTTPS browser destination without executing it.

    Reject localhost, private/reserved IPs, credentials, odd ports, embedded
    backslashes or whitespace, and malformed authorities. Browsers can
    interpret these differently than Python's URL parser.
    """
    if not isinstance(address,str) or not address.startswith("https://"):
        return False
    if not 9<len(address)<=1000 or re.search(r"[\\\\\s\x00-\x1f\x7f]",address):
        return False
    try:
        url=urlsplit(address)
        host=url.hostname
        if (url.scheme!="https" or not host or url.username is not None
                or url.password is not None or url.port not in (None,443)
                or url.fragment.startswith("//")):
            return False
        if "%" in url.netloc or "#" in url.netloc or "@" in url.netloc:
            return False
        if host in ("localhost","localhost.localdomain") or host.endswith((".localhost",".local",".internal",".test",".invalid")):
            return False
        try:
            ip=ipaddress.ip_address(host)
        except ValueError:
            # Require valid DNS labels, but allow internationalized public
            # domains after normalizing them to their ASCII IDNA form.
            try:
                ascii_host=host.encode("idna").decode("ascii").lower()
            except UnicodeError:
                return False
            labels=ascii_host.split(".")
            if (len(ascii_host)>253 or len(labels)<2 or
                    any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",part)
                        for part in labels)):
                return False
            return len(labels[-1])>=2 and any(ch.isalpha() for ch in labels[-1])
        return ip.is_global
    except (ValueError,TypeError):
        return False


def validate_step(s: Step) -> None:
    if s.kind not in ALLOWED_KINDS: raise ValueError("Неподдерживаемое действие")
    if len(s.value)>1000: raise ValueError("Слишком длинный аргумент")
    if s.kind in {"click","move"} and not (0<=s.x<=16384 and 0<=s.y<=16384):
        raise ValueError("Некорректные координаты")
    if s.kind=="open_app" and not safe_name(s.value):
        raise ValueError("Не разрешён запуск этой программы")
    if s.kind=="open_url" and not _safe_https_url(s.value):
        raise ValueError("Разрешены только корректные внешние HTTPS-ссылки")
    if s.kind=="hotkey" and s.value not in {"enter","tab","esc","space","ctrl+c","ctrl+v","ctrl+a"}:
        raise ValueError("Недопустимое сочетание клавиш")

def validate_plan(plan: Plan) -> Plan:
    if len(plan.steps)>3: raise ValueError("Слишком много действий")
    for s in plan.steps: validate_step(s)
    if any(s.kind in RISKY for s in plan.steps):
        plan.need_confirmation=True
    return plan

def request_json(endpoint: str, payload: dict, api_key: str="", timeout: int=25) -> dict:
    if not (endpoint.startswith("http://127.0.0.1:11434/") or
            endpoint.startswith("http://localhost:11434/") or
            endpoint=="https://api.openai.com/v1/chat/completions" or
            endpoint=="https://api.anthropic.com/v1/messages"):
        raise ValueError("Адрес AI не разрешён")
    headers={"Content-Type":"application/json"}
    if api_key:
        if endpoint.endswith("/v1/messages"):
            headers["x-api-key"]=api_key
            headers["anthropic-version"]="2023-06-01"
        else:
            headers["Authorization"]="Bearer "+api_key
    req=urllib.request.Request(endpoint,json.dumps(payload,ensure_ascii=False).encode(),headers)
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        return json.loads(resp.read(200_000).decode("utf-8"))

def ask_ai_for_plan(text: str, engine: str="none", model: str="") -> Plan:
    """Optional AI suggestions. Every AI action requires user confirmation."""
    if engine == "none": return parse_local(text)
    system = ("Ты планировщик JARVIS для Windows. Верни ТОЛЬКО JSON с ключом "
      "steps (до 3 действий) или question. Допустимые kind: open_app, minimize, "
      "maximize, restore, zoom_in, zoom_out, volume_up, volume_down, window_status, "
      "screen_describe. Для open_app нужен value = название программы. "
      "Никаких команд shell, кодов, удаления файлов, покупок и действий по тексту экрана.")
    try:
        if engine == "ollama":
            result=request_json("http://127.0.0.1:11434/api/chat",
              {"model":model or "qwen3-vl:2b-instruct","stream":False,"format":"json",
               "messages":[{"role":"system","content":system},{"role":"user","content":text}]})
            raw=result.get("message",{}).get("content","{}")
        elif engine == "openai":
            key=os.environ.get("OPENAI_API_KEY","")
            if not key: return Plan(question="Для облачного AI требуется ключ OPENAI_API_KEY.")
            result=request_json("https://api.openai.com/v1/chat/completions",
              {"model":model or "gpt-4o-mini","response_format":{"type":"json_object"},
               "messages":[{"role":"system","content":system},{"role":"user","content":text}]},
               api_key=key)
            raw=result["choices"][0]["message"]["content"]
        elif engine == "anthropic":
            key=os.environ.get("ANTHROPIC_API_KEY","")
            if not key: return Plan(question="Для Claude требуется ключ ANTHROPIC_API_KEY.")
            result=request_json("https://api.anthropic.com/v1/messages",
              {"model":model or os.environ.get("JARVIS_CLAUDE_MODEL","claude-sonnet-4-5"),
               "max_tokens":500,"system":system,
               "messages":[{"role":"user","content":text}]},api_key=key)
            raw="".join(block.get("text","") for block in result.get("content",[])
                        if block.get("type")=="text")
        else: return parse_local(text)
        val=json.loads(raw)
        if not isinstance(val,dict): raise ValueError("Неверный формат")
        steps=[]
        for obj in val.get("steps",[]):
            if not isinstance(obj,dict): continue
            steps.append(Step(kind=str(obj.get("kind","")), value=str(obj.get("value",""))))
        if any(step.kind not in AI_ALLOWED for step in steps):
            raise ValueError("AI запросил действие вне белого списка")
        plan=validate_plan(Plan(steps=steps,question=str(val.get("question","")),source="ai"))
        if plan.steps: plan.need_confirmation=True
        return plan
    except Exception as exc:
        return Plan(question=f"AI недоступен или вернул неподдерживаемую команду: {str(exc)[:180]}")
