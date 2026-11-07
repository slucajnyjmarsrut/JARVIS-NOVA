# -*- coding: utf-8 -*-
"""Interactive CLI entry point. No writes without an explicit confirmation."""
import argparse
from pathlib import Path
from code_agent import propose, approve_and_write, check_java, check_luau
from code_workspace import starter_project, preview, ChangePlan
from code_languages import SUPPORTED
from code_checks import check_project

def main():
    parser = argparse.ArgumentParser(description='JARVIS NOVA universal coding assistant')
    parser.add_argument('language', choices=sorted(SUPPORTED))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--task', help='Generate project with local Ollama')
    parser.add_argument('--starter', help='Create a starter project with this name')
    args = parser.parse_args()
    if bool(args.task) == bool(args.starter):
        parser.error('Choose exactly one of --task or --starter')
    if args.task:
        result = propose(args.task, args.language, args.directory)
    else:
        plan = starter_project(args.language, args.starter)
        result = type('Result', (), {'plan': plan, 'changes': preview(plan, args.directory)})()
    print('Изменения:')
    for item in result.changes:
        print(f"  {item['action']}: {item['path']}")
    if input('Записать новые файлы? Введи ДА: ').strip() != 'ДА':
        print('Отменено, файлы не изменены')
        return
    approve_and_write(result, args.directory, approved=True)
    print('Проверка:', check_project(args.language,args.directory))

if __name__ == '__main__':
    main()
