# -*- coding: utf-8 -*-
"""Reviewable coding window for JARVIS; model generation runs off the UI thread.

Uses JARVIS's already-bundled local Qwen when available, or loopback Ollama.
No silent file writes, shell commands, or network code upload.
"""
from __future__ import annotations
import os
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from code_autopilot import generate_and_check, install_reviewed
from code_workspace import starter_project, preview, WorkspaceError
from code_agent import CodeResult, request_local_model
from code_languages import SUPPORTED, LANGUAGE_LABELS
from code_checks import check_project
from roblox_world_builder import build_world, build_model, THEMES, MODELS, SIZES
from code_project_engine import build_complete_project
from code_quality_review import review_change_plan
from code_test_sandbox import run_python_tests


class CodeWindow(tk.Toplevel):
    def __init__(self, master=None, *, language='java', task=''):
        if master is None:
            master=tk.Tk()
            master.withdraw()
            self._standalone_root=master
        super().__init__(master)
        self.title('JARVIS NOVA — Универсальный ИИ-разработчик')
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.geometry('800x650')
        self.language=tk.StringVar(value=language if language in SUPPORTED else 'python')
        self.folder=tk.StringVar()
        self.task=tk.StringVar(value=task)
        self.result=None
        self.modify_existing=tk.BooleanVar(value=False)
        self.full_project=tk.BooleanVar(value=True)
        self.world_theme=tk.StringVar(value='forest')
        self.world_size=tk.IntVar(value=384)
        self.model_kind=tk.StringVar(value='house')
        self._generation_busy=False
        frame=ttk.Frame(self,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Язык программирования').pack(anchor='w')
        ttk.Combobox(frame,textvariable=self.language,
                     values=sorted(SUPPORTED),state='readonly').pack(fill='x')
        ttk.Label(frame,text='Новая папка проекта (существующие файлы не перезаписываются)').pack(anchor='w',pady=(8,0))
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Entry(row,textvariable=self.folder).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Выбрать',command=self.choose).pack(side='left')
        ttk.Checkbutton(frame,text='Изменять существующий проект (с резервными копиями и подтверждением)',
                        variable=self.modify_existing).pack(anchor='w',pady=(7,0))
        ttk.Checkbutton(frame,
            text='Полный проект: архитектура → функции → тесты и документация (3 шага)',
            variable=self.full_project).pack(anchor='w')
        ttk.Label(frame,text='Задача (для генерации) или имя проекта (для шаблона)').pack(anchor='w',pady=(8,0))
        ttk.Entry(frame,textvariable=self.task).pack(fill='x')
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
        self.gen=ttk.Button(bar,text='Создать и проверить код',command=self.generate)
        self.gen.pack(side='left')
        self.starter_button=ttk.Button(bar,text='Создать шаблон',command=self.starter)
        self.starter_button.pack(side='left',padx=6)
        self.write=ttk.Button(bar,text='Подтвердить запись',command=self.install,state='disabled')
        self.write.pack(side='right')
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=(0,8))
        ttk.Button(actions,text='Открыть папку проекта',command=self.open_project).pack(side='left')
        ttk.Button(actions,text='Открыть IDE',command=self.open_ide).pack(side='left',padx=8)
        self.tests_button=ttk.Button(
            actions,text='Тесты Python в Docker (с подтверждением)',
            command=self.test_reviewed_project,state='disabled')
        self.tests_button.pack(side='left',padx=(8,0))
        roblox=ttk.LabelFrame(frame,text='Roblox Studio: генерация 3D-моделей и карт')
        roblox.pack(fill='x',pady=(0,7))
        row=ttk.Frame(roblox);row.pack(fill='x',padx=8,pady=5)
        ttk.Label(row,text='Карта:').pack(side='left')
        ttk.Combobox(row,textvariable=self.world_theme,
                     values=THEMES,width=12,state='readonly').pack(side='left',padx=3)
        ttk.Combobox(row,textvariable=self.world_size,
                     values=SIZES,width=6,state='readonly').pack(side='left',padx=3)
        ttk.Button(row,text='Создать карту + план',command=self.create_roblox_world).pack(side='left',padx=4)
        ttk.Label(row,text='3D-модель:').pack(side='left',padx=(12,2))
        ttk.Combobox(row,textvariable=self.model_kind,
                     values=MODELS,width=15,state='readonly').pack(side='left',padx=3)
        ttk.Button(row,text='Создать 3D-модель + PBR',
                   command=self.create_roblox_model).pack(side='left',padx=4)
        ttk.Label(frame,text='Предварительный просмотр кода и результаты проверки:').pack(anchor='w')
        self.log=tk.Text(frame,wrap='word',font=('Consolas',10))
        self.log.pack(fill='both',expand=True)
        self.show('Выбери пустую папку, опиши задачу, затем проверь код и подтверди запись.\n'
                  'Компиляторы и проверки работают только если установлены. '
                  'Roblox Studio Play Test, запуск и проверка функций выполняются отдельно.')

    def _close(self):
        self.destroy()
        standalone=getattr(self,'_standalone_root',None)
        if standalone is not None:standalone.destroy()

    def prefill(self,language,task):
        if language in SUPPORTED:
            self.language.set(language)
        if task:
            self.task.set(task[:700])
        self.lift()

    def choose(self):
        folder=filedialog.askdirectory(parent=self)
        if folder:self.folder.set(folder)

    def show(self,message):
        self.log.delete('1.0','end')
        self.log.insert('end',message)

    def _target(self):
        value=self.folder.get().strip()
        if not value or not Path(value).is_absolute():
            raise WorkspaceError('Выбери абсолютный путь к папке проекта')
        return Path(value)

    def _model_generator(self, task, language):
        """Prefer the shared, offline runtime already running inside JARVIS."""
        host=self.master
        if getattr(host,"engine",None)=="freellm":
            return host.freellm_chat.generate_code(task,language)
        runtime=getattr(getattr(host,'trimodal',None),'runtime',None)
        if runtime is None:
            return request_local_model(task,language)
        endpoint=runtime.start()
        return request_local_model(task,language,endpoint=endpoint,model=runtime.config.model)

    def _preview_text(self,plan):
        lines=['Файлы проекта (проверь содержимое до сохранения):']
        for item in plan.files:
            lines.append(f'\n--- {item.path} ---')
            if item.path.endswith('.gltf'):
                # Embedded mesh buffers/PNG textures are base64; avoid flooding
                # Tk with hundreds of KB of unreadable binary serialization.
                lines.append('[glTF 2.0: геометрия и PBR-текстуры, '
                             +str(len(item.content.encode('utf-8')))+
                             ' байт. После записи проверь через 3D Importer.]')
            else:
                lines.append(item.content[:30000]+
                             ('\n[ПРЕВЬЮ ОБРЕЗАНО: полный файл сохраняется]'
                              if len(item.content)>30000 else ''))
        return '\n'.join(lines)

    def starter(self):
        try:
            root=self._target()
            plan=starter_project(self.language.get(),self.task.get().strip())
            changes=preview(plan,root)
            self.result=CodeResult(plan,changes)
            self.show('Шаблон без ИИ. Проверка будет выполнена после записи.\n'+self._preview_text(plan))
            self.write.configure(state='normal')
            self.tests_button.configure(
                state='normal' if self.language.get()=='python' else 'disabled')
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)

    def _roblox_asset(self,kind):
        if self._generation_busy:
            return
        try:
            root=self._target()
            label=self.task.get().strip()
            import re
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',label):
                label='NOVA_Map' if kind=='world' else 'NOVA_Model'
            if kind=='world':
                plan=build_world(label,theme=self.world_theme.get(),
                    size=int(self.world_size.get()),quality='detailed')
            else:
                plan=build_model(label,model_type=self.model_kind.get(),
                    quality='detailed')
            changes=preview(plan,root)
            self.language.set('luau')
            self.result=CodeResult(plan,changes)
            self.show('Roblox Studio: Luau для Edit mode → View → Command Bar. '
                'Для модели также создаётся .gltf с PBR; для карты — SVG-план. '
                'Ничего не выполнялось и не сохранялось. '
                'Проверь скрипт и нажми «Подтвердить запись».\n'
                +self._preview_text(plan))
            self.write.configure(state='normal')
        except Exception as exc:
            messagebox.showerror('Roblox 3D',str(exc),parent=self)

    def create_roblox_world(self):
        self._roblox_asset('world')

    def create_roblox_model(self):
        self._roblox_asset('model')

    def generate(self):
        try:
            root=self._target()
            language=self.language.get()
            task=self.task.get().strip()
            existing=self.modify_existing.get()
            full_project=self.full_project.get()
            if not 1<=len(task)<=3000:raise WorkspaceError('Опиши задачу (1–3000 символов)')
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)
            return
        if self._generation_busy:return
        if getattr(self.master,"engine",None)=="freellm":
            if not messagebox.askyesno(
                "Подтвердить отправку кода в FreeLLM",
                "Задача и, при редактировании существующего проекта, исходные файлы "
                "будут переданы через FreeLLM подключённому ИИ-провайдеру. "
                "Не отправляйте пароли, токены и конфиденциальные данные. Продолжить?",
                parent=self):
                return
        self._generation_busy=True
        self.gen.configure(state='disabled')
        self.starter_button.configure(state='disabled')
        self.write.configure(state='disabled')
        self.tests_button.configure(state='disabled')
        self.result=None
        self.show('ИИ создаёт проект и проверяет его. Файлы ещё не меняются.')
        def worker():
            try:
                if full_project:
                    result=build_complete_project(task,language,
                        generator=self._model_generator,workspace=root if existing else None)
                else:
                    result=generate_and_check(task,language,
                        generator=self._model_generator,
                        workspace=root if existing else None)
                preview(result.plan,root)
                self._on_ui(lambda:self.ready(result))
            except Exception as exc:
                msg=str(exc)
                self._on_ui(lambda:self.show('Ошибка: '+msg[:300]))
            finally:
                self._on_ui(self._unblock)
        threading.Thread(target=worker,daemon=True,name='jarvis-code-worker').start()

    def _on_ui(self,callback):
        try:
            if self.winfo_exists():self.after(0,callback)
        except (RuntimeError,tk.TclError):
            pass

    def _unblock(self):
        self._generation_busy=False
        self.gen.configure(state='normal')
        self.starter_button.configure(state='normal')

    def ready(self,result):
        self.result=result
        review=review_change_plan(result.plan)
        findings=[
            f'{f.severity.upper()} {f.path}:{f.line}: {f.message}'
            for f in review.findings]
        lines=['Язык: '+LANGUAGE_LABELS.get(result.plan.language,result.plan.language),
               'Инженерная рецензия (AST, без запуска): '+review.summary(),
               *findings[:30],
               'Статическая проверка: '+('ПРОЙДЕНА' if result.verified else 'НЕ ПОДТВЕРЖДЕНА'),
               'Важное ограничение: JARVIS не запускает сгенерированный код и тесты.',
               *[f'Попытка {a.number}: {a.status}; {a.diagnostics}' for a in result.attempts],
               self._preview_text(result.plan)]
        self.show('\n'.join(lines))
        if result.attempts and result.attempts[-1].status not in ('passed','partial'):
            self.write.configure(state='disabled')
        else:
            self.write.configure(state='normal')
        self.tests_button.configure(
            state='normal' if result.plan.language=='python' else 'disabled')

    def test_reviewed_project(self):
        """Opt-in isolated test of proposed Python files, before disk install."""
        if self._generation_busy or self.result is None:
            return
        plan=self.result.plan
        if plan.language!='python':
            messagebox.showinfo(
                'Docker-тесты','Сейчас поддерживаются только Python-проекты.',
                parent=self)
            return
        if (not isinstance(self.result,CodeResult)
                and self.result.workspace is not None):
            messagebox.showinfo(
                'Редактируемый проект',
                'Для существующего проекта сначала сохрани подтверждённые '
                'изменения, затем проверь собранный проект в Docker отдельно. '
                'Здесь тестируется только новая генерация, без доступа '
                'к старым исходникам.',
                parent=self)
            return
        if not messagebox.askyesno(
            'Изолированная проверка Python',
            'Создать временную копию только Python-файлов проекта и '
            'выполнить тесты в Docker?\n\n'
            'Требуется уже установленный Docker и локальный образ '
            'python:3.12-slim. Интернет в контейнере отключён, '
            'исходники только для чтения. Это не абсолютная песочница; '
            'не запускай заведомо вредоносные программы.',
            parent=self):
            return
        self._generation_busy=True
        self.tests_button.configure(state='disabled')
        self.gen.configure(state='disabled')
        self.status_note='Docker: проверка проекта без сети и без установки пакетов.'
        self.log.insert('end','\n\n'+self.status_note+'\n')
        def worker():
            try:
                with tempfile.TemporaryDirectory(prefix='jarvis-test-proposal-') as tmp:
                    root=Path(tmp)
                    for item in plan.files:
                        if not item.path.endswith('.py'):
                            continue
                        target=root/item.path
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_text(item.content,encoding='utf-8')
                    report=run_python_tests(root,confirmed=True)
                summary=(
                    '\nDOCKER: '+report.status.upper()+
                    '; тестов: '+str(report.tests_run)+
                    '; проверено файлов: '+str(report.inspected_files)+
                    '\n'+report.output[-9000:]+
                    '\nЭто результат тестов в контейнере, '
                    'а не сертификат безопасности.\n')
            except Exception as exc:
                summary='\nDocker-тесты не выполнены: '+str(exc)[:500]+'\n'
            def finish():
                self._generation_busy=False
                self.gen.configure(state='normal')
                self.tests_button.configure(state='normal')
                self.log.insert('end',summary)
                self.log.see('end')
            self._on_ui(finish)
        threading.Thread(
            target=worker,daemon=True,name='jarvis-reviewed-docker-tests').start()

    def install(self):
        if self._generation_busy or not self.result:return
        try:
            root=self._target()
            changes=preview(self.result.plan,root)
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)
            return
        editable=not isinstance(self.result,CodeResult) and self.result.workspace is not None
        engineering=review_change_plan(self.result.plan)
        if engineering.risk_count and not messagebox.askyesno(
            'Потенциально опасные операции',
            f'AST-рецензия обнаружила {engineering.risk_count} '
            'операций, требующих ручной проверки.\n'
            'Посмотри список в окне исходников. '
            'Разрешить продолжить только после личной проверки?',
            parent=self):
            return
        if any(item['action']=='replace' for item in changes) and not editable:
            messagebox.showerror('Защита файлов','Для правок существующего проекта нужно включить режим редактирования и повторно проверить код.',parent=self)
            return
        if not messagebox.askyesno('Подтверждение',
                f'Применить {len(changes)} файлов в:\n{root}\n'
                + ('Существующие файлы будут обновлены, резервные копии сохранены.\n' if editable else '')
                + '\nТы проверил код и разрешаешь эти изменения?',parent=self):return
        try:
            if isinstance(self.result,CodeResult):
                from code_agent import approve_and_write
                paths=approve_and_write(self.result,root,approved=True)
            else:
                paths=install_reviewed(self.result,root,confirmed=True)
            check=check_project(self.result.plan.language,root)
            self.show('Файлы записаны:\n'+'\n'.join(paths)+'\n\nПроверка: '+str(check))
            self.write.configure(state='disabled')
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)

    def open_project(self):
        try:
            path=self._target()
            if not path.is_dir():raise FileNotFoundError('Сначала создай проект')
            if os.name != 'nt':raise OSError('Открытие проводника доступно только на Windows')
            os.startfile(str(path))
        except Exception as exc:messagebox.showerror('Папка проекта',str(exc),parent=self)

    def open_ide(self):
        try:
            desktop=getattr(self.master,'desktop',None)
            if desktop is None:raise OSError('Запусти окно программирования из JARVIS NOVA')
            app='Roblox Studio' if self.language.get()=='luau' else 'Visual Studio Code'
            desktop.open_app(app)  # exact installed Start Menu shortcut; no shell
            self.show(f'Открыто: {app}.\n\n'+
                      ('Для Roblox подключи Rojo или импортируй скрипт в ServerScriptService и запусти Play Test.'
                       if self.language.get()=='luau' else 'Открой созданную папку проекта в редакторе.'))
        except Exception as exc:messagebox.showerror('IDE',str(exc),parent=self)

if __name__ == '__main__':
    window=CodeWindow()
    window.master.mainloop()
