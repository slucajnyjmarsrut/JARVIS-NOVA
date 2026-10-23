# -*- coding: utf-8 -*-
"""Confidence-guided Russian Whisper decoding, with no extra I/O.

Second pass is reserved for user-activated low-confidence commands or unusually
short Russian hypotheses; background audio never causes the extra decode.
These heuristics do NOT authorize commands: that remains voice_engine's job.
"""
from __future__ import annotations
import math
import re
from difflib import SequenceMatcher

from agent_core import strip_wake


def _segments(result):
    if not isinstance(result,dict):
        return []
    return [s for s in result.get("segments",()) if isinstance(s,dict)]


def _number(value,default):
    try:
        number=float(value)
        return number if math.isfinite(number) else default
    except (TypeError,ValueError,OverflowError):
        return default


def transcript_confidence(result):
    """Return estimated score from Whisper's own per-segment metadata.

    Whisper numbers are not calibrated probabilities. Low score means *try a
    second decode*, not that the text is safe to execute.
    """
    chunks=_segments(result)
    if not chunks:
        return None
    avg=sum(_number(s.get("avg_logprob"),-2.0) for s in chunks)/len(chunks)
    compression=max(_number(s.get("compression_ratio"),1.0) for s in chunks)
    silence=max(_number(s.get("no_speech_prob"),0.0) for s in chunks)
    return avg-max(0.0,compression-2.2)*0.5-max(0.0,silence-0.5)*.35


def should_refine(result, authorized=False):
    """Refine only if F9/Vosk wake or first-pass wake actually authorized it."""
    if not authorized:
        return False
    content=str(result.get("text","") or "").strip() if isinstance(result,dict) else ""
    if not content or len(content)<4:
        return True
    confidence=transcript_confidence(result)
    if confidence is not None and confidence < -.76:
        return True
    # A weak *last segment* can hide behind a good average score: this often
    # affects Russian word endings. Only retry speech-bearing spans of 180ms+.
    chunks=_segments(result)
    return len(chunks)>1 and any(
        _number(s.get("avg_logprob"),0.0)<-1.05
        and _number(s.get("no_speech_prob"),1.0)<.4
        and _number(s.get("end"),0.0)-_number(s.get("start"),0.0)>=.18
        for s in chunks
    )


def russian_app_vocabulary(result):
    """Optional local Whisper vocabulary hint, NOT recognized command text.

    Only call this for an already activated command during a quality retry.
    Never prepend verbs or a wake word, so hints cannot authorize actions.
    """
    if not isinstance(result,dict):
        return None
    phrase=strip_wake(str(result.get("text","") or "")).casefold().strip()
    if not re.match(r"^(?:открой|запусти|включи)\b",phrase):
        return None
    return ("Телеграм, Telegram, Дискорд, Discord, Стим, Steam, "
            "Гугл Хром, Google Chrome, Блокнот, Проводник, Калькулятор.")


def suspicious_wake_prefix(result):
    """Flag a weak, *untrusted* near-wake for a small-model verification pass.

    Similarity is NEVER authorization: only an exact wake confirmed by the
    more accurate Whisper model may enter the normal command pipeline.
    Ignore well-recognized text, missing segment metadata and background noise.
    """
    if not isinstance(result,dict):
        return False
    score=transcript_confidence(result)
    if score is None or score>=-.76:
        return False
    utterance=str(result.get("text","") or "").casefold().strip(" \\t«»\\\"'")
    words=re.findall(r"[а-яё]+",utterance)
    if not words:
        return False
    # Optional colloquial address; never fuzzy-match arbitrary later words.
    first=words[1] if words[0] in ("эй","окей","слушай","ну","привет") and len(words)>1 else words[0]
    if not 5<=len(first)<=9 or not first.startswith(("дж","ж","д")):
        return False
    return max(SequenceMatcher(None,first,real).ratio()
               for real in ("джарвис","жарвис"))>=.79


# One-word commands/answers where another expensive decode rarely helps.
_KNOWN_SHORT_RU = frozenset({
    "привет", "здравствуй", "спасибо", "пожалуйста", "пока", "хорошо",
    "нормально", "отмена", "прекрати", "джарвис", "жарвис",
    "открой", "запусти", "включи", "выключи", "сверни",
    "блокнот", "браузер", "калькулятор", "проводник",
    "телеграм", "дискорд",
})
# A second decode must never turn a dubious single word into a new computer action.
_NEW_ACTION = re.compile(
    r"\b(?:открой|запусти|включи|выключи|закрой|удали|нажми|"
    r"напечатай|введи|напиши|кликни|перемести|отправь|сверни|разверни)\b",
    re.I,
)


def should_refine_short_phrase(result, authorized=False):
    """Detect short possibly mangled Russian utterances, even if confidence is high.

    In accurate mode this may spend one extra local beam-search decode to
    recover phrases such as 'что делаешь' transcribed as a single false word.
    It is an ASR hint only; never grants wake or device permissions.
    """
    if not authorized or not isinstance(result,dict):
        return False
    text=strip_wake(str(result.get("text","") or "")).casefold()
    words=re.findall(r"[а-яё]+",text)
    if len(words)!=1 or not 5<=len(words[0])<=12 or words[0] in _KNOWN_SHORT_RU:
        return False
    confidence=transcript_confidence(result)
    # Normal low-confidence retry already handles that case. Do not refine
    # missing-metadata adapters or likely-silent audio based on text alone.
    if confidence is None or confidence<-.76:
        return False
    return max(_number(s.get("no_speech_prob"),0.0) for s in _segments(result))<.45


def prefer_short_refined(first,second):
    """Accept a clearer second hypothesis without inventing a computer action."""
    if not isinstance(first,dict) or not isinstance(second,dict):
        return first
    a=str(first.get("text","") or "").strip()
    b=str(second.get("text","") or "").strip()
    if not b:
        return first
    original=strip_wake(a)
    candidate=strip_wake(b)
    if _NEW_ACTION.search(candidate) and not _NEW_ACTION.search(original):
        return first
    a_score=transcript_confidence(first)
    b_score=transcript_confidence(second)
    if a_score is None or b_score is None or b_score<-.7:
        return first
    return second if b_score>a_score+.04 else first


def prefer_refined(first,second):
    """Pick the more credible result; avoid executing weak hallucinations."""
    a=str(first.get("text","") or "").strip() if isinstance(first,dict) else ""
    b=str(second.get("text","") or "").strip() if isinstance(second,dict) else ""
    if not a:
        return second if b else first
    if not b:
        # A low-quality original that disappears with a stronger search
        # should not be executed as a command.
        confidence=transcript_confidence(first)
        return second if confidence is not None and confidence < -1.1 else first
    ac=transcript_confidence(first)
    bc=transcript_confidence(second)
    if ac is not None and bc is not None:
        return second if bc>ac+.03 else first
    # Fake models and some adapters omit per-segment metadata. Their second
    # pass still helps blank transcription, but cannot validate disagreements.
    return first
