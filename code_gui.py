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
from uuid import uuid4
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from code_autopilot import Attempt, AutopilotResult, generate_and_check, install_reviewed
from code_workspace import starter_project, preview, WorkspaceError
from code_agent import CodeResult, request_local_model
from code_languages import SUPPORTED, LANGUAGE_LABELS
from code_checks import check_project
from roblox_world_builder import build_world, build_model, THEMES, MODELS, SIZES
from code_project_engine import build_one_shot_project, describe_execution_plan
from code_quality_review import review_change_plan, unified_plan_diff
from code_test_sandbox import run_python_tests
from code_test_repair import repair_after_tests


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
        # Draft destination only; not created until the user approves writing.
        self.folder=tk.StringVar(value=str(
            Path.home() / "JARVIS-NOVA-Projects" / ("Project-" + uuid4().hex[:8])))
        self.task=tk.StringVar(value=task)
        self.result=None
        self.modify_existing=tk.BooleanVar(value=False)
        self.full_project=tk.BooleanVar(value=True)
        self.world_theme=tk.StringVar(value='forest')
        self.world_size=tk.IntVar(value=384)
        self.model_kind=tk.StringVar(value='house')
        self._generation_busy=False
        self._last_test_gate_status=None
        self._auto_save_target=None
        self._coder_opt_in=False
        self._coder_checked=False
        self._coder_choice=None
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
            text='Полный проект: план → шаги с проверкой → итоговая проверка',
            variable=self.full_project).pack(anchor='w')
        ttk.Label(frame,text='Задача (для генерации) или имя проекта (для шаблона)').pack(anchor='w',pady=(8,0))
        ttk.Entry(frame,textvariable=self.task).pack(fill='x')
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
        self.gen=ttk.Button(bar,text='Составить план → выполнить и проверить',command=self.generate)
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
        repairs=ttk.Frame(frame);repairs.pack(fill='x',pady=(0,6))
        self.repair_button=ttk.Button(
            repairs,text='Исправить по тестам (до 2)',
            command=self.repair_using_test_feedback,state='disabled')
        self.repair_button.pack(side='left',padx=(0,6))
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
        self.show('Опиши задачу: JARVIS создаст архитектуру, реализацию и тесты '
                  'за один запуск. Новая папка предложена автоматически; '
                  'файлы появятся только после подтверждения записи. '
                  'Внешние среды и Roblox Play Test проверяются отдельно.')

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
        """Only the dedicated programmer model; never use Vision as coder."""
        host=self.master
        if getattr(host,"engine",None)=="freellm":
            return host.freellm_chat.generate_code(task,language)
        if not self._coder_opt_in:
            raise WorkspaceError(
                "ИИ-программист не был разрешён. Отдельно подтверди "
                "использование Qwen Coder в окне программирования.")
        if not self._coder_checked:
            self._coder_checked=True
            try:
                from local_coder_models import best_installed_coder
                found=best_installed_coder(confirmed=True)
                self._coder_choice=found.name if found is not None else None
            except (OSError,ValueError,RuntimeError,TypeError):
                self._coder_choice=None
        if self._coder_choice is None:
            raise WorkspaceError(
                "Отдельный ИИ-программист не подключён: запусти Ollama "
                "на 127.0.0.1:11434 и установи Qwen2.5-Coder:7b "
                "через «ИИ ПО ЗАДАЧАМ». Vision Qwen не подменяет программиста.")
        return request_local_model(
            task,language,endpoint="http://127.0.0.1:11434",
            model=self._coder_choice)

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
            self._last_test_gate_status=None
            self.show('Шаблон без ИИ. Проверка будет выполнена после записи.\n'+self._preview_text(plan))
            self.write.configure(state='normal')
            self.tests_button.configure(
                state='normal' if self.language.get()=='python' else 'disabled')
            self.repair_button.configure(
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

    def generate(self, *, auto_save=False):
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
        sandbox_consent=False
        auto_write=False
        self._auto_save_target=None
        if auto_save and full_project and language=="python" and not existing:
            from code_autosave_policy import safe_new_project_folder
            if safe_new_project_folder(root):
                auto_write=messagebox.askyesno(
                    "Автономное создание нового проекта",
                    "Разрешить одним подтверждением проверить Python-код "
                    "в изолированном Docker без сети (до 5 попыток исправления) "
                    "и, только если независимые тесты пройдут, сохранить "
                    f"НОВЫЕ файлы в папку:\n{root}\n\n"
                    "Существующие файлы не перезаписываются. "
                    "Тесты не запускаются на Windows. "
                    "Docker изолирует не абсолютно; требуется локальный образ. "
                    "Если на 127.0.0.1:11434 уже работает Ollama, можно "
                    "однократно проверить список моделей и использовать "
                    "уже установленную модель для кода (до 14B параметров). "
                    "Новые модели не скачиваются, в облако код не уходит.",
                    parent=self)
                sandbox_consent=auto_write
        elif full_project and language=="python" and not existing:
            sandbox_consent=messagebox.askyesno(
                "Автопроверка Python за один запуск",
                "После генерации проверять проект в изолированном Docker "
                "без интернета и пробовать до пяти самостоятельных "
                "исправлений? Код запускается только в ограниченном "
                "контейнере, не на компьютере. Изоляция не абсолютна. "
                "Требуется уже установленный Docker и локальный "
                "образ python:3.12-slim. Без согласия останется только "
                "проверка синтаксиса. При согласии можно также проверить "
                "запущенную локальную Ollama и выбрать уже установленную "
                "кодовую модель без скачивания.",parent=self)
        coder_opt_in=bool(sandbox_consent)
        if (getattr(self.master, "engine", None)!="freellm"
                and not coder_opt_in):
            coder_opt_in=messagebox.askyesno(
                "Отдельный ИИ-программист · Qwen Coder",
                "Программирование выполняет специализированная модель "
                "Qwen2.5-Coder:7b через локальную Ollama "
                "(127.0.0.1:11434), а НЕ Qwen Vision.\n\n"
                "Разрешить проверить установленные кодовые модели и "
                "использовать их для этой задачи? "
                "Новых моделей не скачиваем и в облако код не отправляем. "
                "Если модель отсутствует, открой «ИИ ПО ЗАДАЧАМ» "
                "для её установки после подтверждения.",
                parent=self)
        self._generation_busy=True
        self.gen.configure(state='disabled')
        self.starter_button.configure(state='disabled')
        self.write.configure(state='disabled')
        self.tests_button.configure(state='disabled')
        self.repair_button.configure(state='disabled')
        self._last_test_gate_status=None
        self._auto_save_target=root if auto_write else None
        self._coder_opt_in=bool(coder_opt_in)
        self._coder_checked=False
        self._coder_choice=None
        self.result=None
        if full_project:
            self.show(describe_execution_plan(task,language)+
                "\n\nПодготавливаю черновик. Оригинальные файлы не меняются.\n")
        else:
            self.show('ИИ создаёт проект и проверяет его. Файлы ещё не меняются.')
        def stage_progress(message):
            self._on_ui(lambda msg=message:self._append_plan_progress(msg))
        def worker():
            try:
                if full_project:
                    result=build_one_shot_project(
                        task,language,generator=self._model_generator,
                        workspace=root if existing else None,
                        allow_sandbox_tests=sandbox_consent,
                        stepwise=True,progress=stage_progress)
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

    def _append_plan_progress(self, message):
        if not self.winfo_exists():
            return
        self.log.insert('end',str(message)[:400]+'\n')
        self.log.see('end')

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
        runtime=getattr(getattr(self.master,'trimodal',None),'runtime',None)
        model_label=(
            "FreeLLM (внешний провайдер)" if getattr(self.master,"engine",None)=="freellm"
            else self._coder_choice or
                 (getattr(getattr(runtime,'config',None),'model',None)
                  or "локальная кодовая модель по умолчанию"))
        lines=['Язык: '+LANGUAGE_LABELS.get(result.plan.language,result.plan.language),
               'Модель проекта: '+str(model_label),
               'Инженерная рецензия (AST, без запуска): '+review.summary(),
               *findings[:30],
               'Общая статическая проверка: '+
               ('ПРОЙДЕНА' if result.verified else 'НЕ ПОДТВЕРЖДЕНА'),
               'Отчёт по шагам: выполнено → проверено отдельно → проверено вместе.',
               'Для Python автоматические тесты идут в Docker только после согласия; '
               'проверка синтаксиса других языков не доказывает полную работоспособность.',
               *[f'Попытка {a.number}: {a.status}; {a.diagnostics}' for a in result.attempts],
               'Предлагаемые изменения (unified diff, без записи в проект):',
               unified_plan_diff(result.plan,self._target()),
               self._preview_text(result.plan)]
        self.show('\n'.join(lines))
        if result.attempts and result.attempts[-1].status not in ('passed','partial'):
            self.write.configure(state='disabled')
        else:
            self.write.configure(state='normal')
        allowed_python=(result.plan.language=='python'
                        and result.workspace is None)
        self.tests_button.configure(
            state='normal' if allowed_python else 'disabled')
        self.repair_button.configure(
            state='normal' if allowed_python else 'disabled')
        target=self._auto_save_target
        self._auto_save_target=None  # Never reuse approval across requests.
        if target is not None:
            from code_autosave_policy import save_approved_one_shot
            try:
                if self._target().resolve()!=target.resolve():
                    raise WorkspaceError('Папка проекта изменилась.')
                written=save_approved_one_shot(
                    result,target,authorized=True)
                self.log.insert('end',
                    '\n\nПроект автоматически сохранён после тестов:\n'
                    + '\n'.join(written)
                    + '\nКод на Windows не запускался.\n')
                self.write.configure(state='disabled')
            except Exception as exc:
                self.log.insert('end',
                    '\n\nАвтосохранение не выполнено: '
                    + str(exc)[:400]
                    + '\nПроверь отчёт и повтори вручную.\n')
            self.log.see('end')

    def repair_using_test_feedback(self):
        """Use a bounded Docker-only diagnostic repair loop; never auto-install."""
        if self._generation_busy or self.result is None:
            return
        original=self.result
        if original.plan.language!='python' or (
                not isinstance(original,CodeResult) and original.workspace is not None):
            messagebox.showinfo(
                'Тесты и исправления',
                'Пока доступны только новые Python-проекты. '
                'Редактирование существующих проектов требует '
                'отдельного согласованного обзора всех файлов.',
                parent=self)
            return
        if not messagebox.askyesno(
            'Проверить и исправить Python',
            'Проверить тесты в изолированном Docker без сети и, если они '
            'не проходят, предложить не более двух исправлений с помощью ИИ?\n\n'
            'Код будет обработан как данные в отдельной папке, исходники '
            'не перезаписываются. После проверки будет показан diff.\n'
            'Docker должен быть установлен, образ python:3.12-slim — '
            'уже доступен локально. Изоляция не абсолютна.',
            parent=self):
            return
        if getattr(self.master,'engine',None)=='freellm':
            if not messagebox.askyesno(
                'Передача ошибок и исходников ИИ-провайдеру',
                'В режиме FreeLLM содержимое Python-файлов и сообщения '
                'ошибок тестов будут отправлены подключённому внешнему '
                'провайдеру для исправления. Не передавай токены и '
                'личные данные. Разрешить?',
                parent=self):
                return
        task=self.task.get().strip() or 'Исправить Python-тесты'
        self._generation_busy=True
        self._last_test_gate_status=None
        for button in (self.gen,self.starter_button,self.tests_button,
                       self.repair_button,self.write):
            button.configure(state='disabled')
        self.log.insert('end','\nНачинаю Docker-тесты и не более двух исправлений.\n')
        def worker():
            try:
                repaired=repair_after_tests(
                    task,original.plan,generator=self._model_generator,
                    runner=run_python_tests,confirmed=True,max_repairs=2)
                report='\n'.join(
                    f'Попытка {step.round}: {step.status.upper()}, '
                    f'тестов {step.tests_run}\n{step.diagnostics[-1200:]}'
                    for step in repaired.steps)
                def finish():
                    self._generation_busy=False
                    self.gen.configure(state='normal')
                    self.starter_button.configure(state='normal')
                    self.tests_button.configure(state='normal')
                    self.repair_button.configure(state='normal')
                    self.log.insert('end','\n'+report+'\n')
                    if repaired.success:
                        # Retain staged changes for review; no disk writes.
                        new_result=AutopilotResult(
                            repaired.plan,[Attempt(1,'passed',
                            f'Docker: {repaired.steps[-1].tests_run} tests')],
                            True,None,{})
                        self._last_test_gate_status='passed'
                        self.ready(new_result)
                        self.log.insert('end',
                            '\nDocker-тесты прошли. Это не гарантия '
                            'полной корректности или безопасности.\n')
                    else:
                        self._last_test_gate_status=(
                            'blocked' if any(x.status=='blocked'
                                             for x in repaired.steps)
                            else repaired.steps[-1].status)
                        if self._last_test_gate_status in ('failed','blocked'):
                            self.write.configure(state='disabled')
                        self.log.insert('end',
                            '\nНовая версия НЕ подтверждена тестами. '
                            'Не выдавай её за рабочую.\n')
                    self.log.see('end')
                self._on_ui(finish)
            except Exception as exc:
                msg=str(exc)[:500]
                def error():
                    self._generation_busy=False
                    self._last_test_gate_status='failed'
                    self.gen.configure(state='normal')
                    self.starter_button.configure(state='normal')
                    self.tests_button.configure(state='normal')
                    self.repair_button.configure(state='normal')
                    self.write.configure(state='disabled')
                    self.log.insert('end','\nИсправление прервано: '+msg+'\n')
                    self.log.see('end')
                self._on_ui(error)
        threading.Thread(
            target=worker,daemon=True,name='jarvis-docker-code-repair').start()

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
        self.repair_button.configure(state='disabled')
        self.starter_button.configure(state='disabled')
        self.write.configure(state='disabled')
        self.gen.configure(state='disabled')
        self.status_note='Docker: проверка проекта без сети и без установки пакетов.'
        self.log.insert('end','\n\n'+self.status_note+'\n')
        def worker():
            state='failed'
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
                state=report.status
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
                self._last_test_gate_status=state
                self.gen.configure(state='normal')
                self.starter_button.configure(state='normal')
                self.tests_button.configure(state='normal')
                self.repair_button.configure(state='normal')
                if state in ('failed','blocked'):
                    self.write.configure(state='disabled')
                elif self.result is not None and state=='passed':
                    self.write.configure(state='normal')
                self.log.insert('end',summary)
                self.log.see('end')
            self._on_ui(finish)
        threading.Thread(
            target=worker,daemon=True,name='jarvis-reviewed-docker-tests').start()

    def install(self):
        if self._generation_busy or not self.result:return
        if self._last_test_gate_status in ('failed','blocked'):
            messagebox.showerror(
                'Тесты не пройдены',
                'После неудачных тестов нужна новая исправленная '
                'генерация и повторная проверка.',
                parent=self)
            return
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
