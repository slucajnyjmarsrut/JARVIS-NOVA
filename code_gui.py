# -*- coding: utf-8 -*-
"""Reviewable coding window for JARVIS; model generation runs off the UI thread.

Uses JARVIS's already-bundled local Qwen when available, or loopback Ollama.
No silent file writes, shell commands, or network code upload.
"""
from __future__ import annotations
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from code_autopilot import generate_and_check, install_reviewed
from code_workspace import starter_project, preview, WorkspaceError
from code_agent import CodeResult, request_local_model, check_java, check_luau


class CodeWindow(tk.Toplevel):
    def __init__(self, master=None, *, language='java', task=''):
        if master is None:
            master=tk.Tk()
            master.withdraw()
            self._standalone_root=master
        super().__init__(master)
        self.title('JARVIS NOVA — Java / Roblox Luau')
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.geometry('800x650')
        self.language=tk.StringVar(value=language if language in ('java','luau') else 'java')
        self.folder=tk.StringVar()
        self.task=tk.StringVar(value=task)
        self.result=None
        self.modify_existing=tk.BooleanVar(value=False)
        self._generation_busy=False
        frame=ttk.Frame(self,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Язык программирования').pack(anchor='w')
        ttk.Combobox(frame,textvariable=self.language,values=['java','luau'],state='readonly').pack(fill='x')
        ttk.Label(frame,text='Новая папка проекта (существующие файлы не перезаписываются)').pack(anchor='w',pady=(8,0))
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Entry(row,textvariable=self.folder).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Выбрать',command=self.choose).pack(side='left')
        ttk.Checkbutton(frame,text='Изменять существующий проект (с резервными копиями и подтверждением)',
                        variable=self.modify_existing).pack(anchor='w',pady=(7,0))
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
        ttk.Label(frame,text='Предварительный просмотр кода и результаты проверки:').pack(anchor='w')
        self.log=tk.Text(frame,wrap='word',font=('Consolas',10))
        self.log.pack(fill='both',expand=True)
        self.show('Выбери пустую папку, опиши задачу, затем проверь код и подтверди запись.\n'
                  'Roblox Studio Play Test и тестирование на Windows выполняются отдельно.')

    def _close(self):
        self.destroy()
        standalone=getattr(self,'_standalone_root',None)
        if standalone is not None:standalone.destroy()

    def prefill(self,language,task):
        if language in ('java','luau'):
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
        runtime=getattr(getattr(host,'trimodal',None),'runtime',None)
        if runtime is None:
            return request_local_model(task,language)
        endpoint=runtime.start()
        return request_local_model(task,language,endpoint=endpoint,model=runtime.config.model)

    def _preview_text(self,plan):
        lines=['Файлы проекта (проверь весь код до сохранения):']
        for item in plan.files:
            lines.extend([f'\n--- {item.path} ---',item.content])
        return '\n'.join(lines)

    def starter(self):
        try:
            root=self._target()
            plan=starter_project(self.language.get(),self.task.get().strip())
            changes=preview(plan,root)
            self.result=CodeResult(plan,changes)
            self.show('Шаблон без ИИ. Проверка будет выполнена после записи.\n'+self._preview_text(plan))
            self.write.configure(state='normal')
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)

    def generate(self):
        try:
            root=self._target()
            language=self.language.get()
            task=self.task.get().strip()
            existing=self.modify_existing.get()
            if not 1<=len(task)<=3000:raise WorkspaceError('Опиши задачу (1–3000 символов)')
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)
            return
        if self._generation_busy:return
        self._generation_busy=True
        self.gen.configure(state='disabled')
        self.starter_button.configure(state='disabled')
        self.write.configure(state='disabled')
        self.result=None
        self.show('Локальный ИИ создаёт проект и проверяет его. Файлы ещё не меняются.')
        def worker():
            try:
                result=generate_and_check(task,language,generator=self._model_generator,
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
        lines=['Проверено Java-компилятором: '+('ДА' if result.verified else 'НЕТ'),
               *[f'Попытка {a.number}: {a.status}; {a.diagnostics}' for a in result.attempts],
               self._preview_text(result.plan)]
        self.show('\n'.join(lines))
        if result.attempts and result.attempts[-1].status == 'failed':
            self.write.configure(state='disabled')
        else:
            self.write.configure(state='normal')

    def install(self):
        if self._generation_busy or not self.result:return
        try:
            root=self._target()
            changes=preview(self.result.plan,root)
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc),parent=self)
            return
        editable=not isinstance(self.result,CodeResult) and self.result.workspace is not None
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
            check=check_java(root) if self.result.plan.language=='java' else check_luau(root)
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
