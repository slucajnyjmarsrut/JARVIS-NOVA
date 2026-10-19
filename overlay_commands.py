"""Exact, local and non-privileged voice commands for NOVA window visibility.

Avoid fuzzy substring matches: chat mentioning an overlay must NOT
unexpectedly hide the user's window.
"""
import re


def overlay_intent(utterance: str) -> str | None:
    normalized=re.sub(r"[^\w\s]", " ", str(utterance).casefold().replace("ё","е"))
    words=" ".join(normalized.split())
    # The voice router strips the wake word before reaching handle_text().
    if words.startswith("джарвис "):
        words=words[len("джарвис "):]
    show={
        "покажи интерфейс", "открой интерфейс", "верни интерфейс",
        "покажи главное окно", "открой главное окно", "верни главное окно",
        "покажи окно джарвиса", "верни окно джарвиса",
    }
    hide={
        "скрой интерфейс", "спрячь интерфейс", "сверни интерфейс",
        "покажи оверлей", "открой оверлей", "включи оверлей",
        "скрой окно джарвиса", "сверни окно джарвиса",
    }
    if words in show:
        return "show"
    if words in hide:
        return "hide"
    return None


def preview_line(person, message, limit=72):
    """One safe, unformatted single-line UI preview. Does not write to disk."""
    if not isinstance(message,str):
        message=str(message)
    clean=" ".join(message.split())
    clean="".join(c for c in clean if c.isprintable())
    limit=max(8,min(int(limit),160))
    if len(clean)>limit:
        clean=clean[:limit-1].rstrip()+"…"
    return f"{person}: {clean}" if clean else ""
