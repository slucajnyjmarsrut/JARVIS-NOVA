# -*- coding: utf-8 -*-
"""Offline text-to-speech segmentation. Does not alter the user's request."""
from __future__ import annotations
import re


def split_for_tts(text: str, *, max_chars: int = 280, max_total: int = 4000) -> tuple[str, ...]:
    """Divide long responses into bounded Silero phrases, preserving punctuation.

    No empty tokens or unbounded text passed to the model. Only playback is
    limited; the original response remains complete in the local chat history.
    """
    if not isinstance(text, str):
        return ()
    max_chars=max(40,min(400,int(max_chars)))
    max_total=max(max_chars,min(20000,int(max_total)))
    cleaned=" ".join(text.split())
    if not cleaned:
        return ()
    if len(cleaned)>max_total:
        cleaned=cleaned[:max_total-1].rstrip()+"…"
    sentences=re.split(r"(?<=[.!?…;:])\s+",cleaned)
    chunks=[]
    current=""
    def append_tokens(piece):
        nonlocal current
        words=piece.split(" ")
        for word in words:
            while len(word)>max_chars:
                if current:
                    chunks.append(current)
                    current=""
                chunks.append(word[:max_chars])
                word=word[max_chars:]
            if not word:
                continue
            candidate=(current+" "+word).strip() if current else word
            if len(candidate)>max_chars:
                if current:
                    chunks.append(current)
                current=word
            else:
                current=candidate
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence)>max_chars:
            if current:
                chunks.append(current)
                current=""
            append_tokens(sentence)
        elif current and len(current)+1+len(sentence)<=max_chars:
            current+=" "+sentence
        else:
            if current:
                chunks.append(current)
            current=sentence
    if current:
        chunks.append(current)
    return tuple(c for c in chunks if c)
