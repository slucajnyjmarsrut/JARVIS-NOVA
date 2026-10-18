# -*- coding: utf-8 -*-
"""Local, read-only game discovery; never execute a path from voice or metadata."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
import re

from agent_core import normalize, UNSAFE_APPS
from self_improve import safe_name


@dataclass(frozen=True)
class GameChoice:
    label: str
    source: str  # start_menu or steam
    target: str  # safe shortcut name or numeric registered Steam app ID


def _vdf_string(text: str, key: str) -> str:
    match = re.search(r'^\\s*"'+re.escape(key)+r'"\\s+"((?:\\\\.|[^"\\\\])*)"', text, re.I | re.M)
    return match.group(1).replace('\\\\', '\\') if match else ''


class GameCatalog:
    """Only names read from Start shortcuts and manifests in known Steam folders."""
    def __init__(self, steam_roots: tuple[Path, ...] | None = None):
        if steam_roots is not None:
            self.steam_roots = tuple(map(Path, steam_roots))
        else:
            candidates = (os.getenv('PROGRAMFILES(X86)', ''), os.getenv('PROGRAMFILES', ''))
            self.steam_roots = tuple(Path(root) / 'Steam' for root in candidates if root)

    def _steam_libraries(self):
        found = set()
        for base in self.steam_roots:
            library = base / 'steamapps'
            if library.is_dir():
                found.add(library)
            vdf = library / 'libraryfolders.vdf'
            try:
                if not vdf.is_file() or vdf.stat().st_size > 1_000_000:
                    continue
                data = vdf.read_text('utf-8-sig', errors='replace')
                for match in re.finditer(r'"path"\\s+"((?:\\\\.|[^"\\\\]){1,600})"', data, re.I):
                    target = Path(match.group(1).replace('\\\\', '\\')) / 'steamapps'
                    if target.is_dir():
                        found.add(target)
            except (OSError, ValueError):
                continue
        return sorted(found)

    def available(self, start_menu_names=()):
        result = {}
        for name in start_menu_names:
            if safe_name(name) and normalize(name) not in UNSAFE_APPS:
                key = normalize(name)
                result.setdefault(key, GameChoice(name, 'start_menu', name))
        for library in self._steam_libraries():
            try:
                manifests = sorted(library.glob('appmanifest_*.acf'))[:1500]
            except OSError:
                continue
            for file in manifests:
                try:
                    if file.stat().st_size > 200_000 or not file.is_file():
                        continue
                    app_id = file.stem.removeprefix('appmanifest_')
                    if not re.fullmatch(r'[1-9][0-9]{0,11}', app_id):
                        continue
                    content = file.read_text('utf-8-sig', errors='replace')
                    title = _vdf_string(content, 'name')
                    if not safe_name(title) or normalize(title) in UNSAFE_APPS:
                        continue
                    result[normalize(title)] = GameChoice(title, 'steam', app_id)
                except (OSError, ValueError):
                    continue
        return tuple(sorted(result.values(), key=lambda item: normalize(item.label)))

    def find(self, name, start_menu_names=()):
        if not safe_name(name):
            return None
        matches = [game for game in self.available(start_menu_names) if normalize(game.label) == normalize(name)]
        return matches[0] if len(matches) == 1 else None

    def validate_steam(self, choice: GameChoice):
        if choice.source != 'steam' or not re.fullmatch(r'[1-9][0-9]{0,11}', choice.target):
            return False
        return any(game.source == 'steam' and game.target == choice.target and
                   normalize(game.label) == normalize(choice.label) for game in self.available(()))
