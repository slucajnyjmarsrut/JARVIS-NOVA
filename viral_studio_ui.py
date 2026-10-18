# -*- coding: utf-8 -*-
"""Native Tk dialog for Viral Studio. Footage stays local; publishing is manual."""
from __future__ import annotations
import os
import queue
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from uuid import uuid4

from viral_studio import (ViralStudioError, create_local_brief, research_trends,
                          template_brief, save_brief, load_brief, render_video)
from channel_audience import import_csv, analyze, recommend_topic, report as channel_report
from creator_experts import expert_report
from video_forecast import assess_video, store_assessment


def _home():
    # Data are preserved by Inno Setup upgrades/uninstalls.
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'JarvisNova' / 'viral_studio'


class ViralStudioWindow(tk.Toplevel):
    def __init__(self, parent, speaker=None):
        super().__init__(parent)
        self.title('JARVIS NOVA — Вирусные ролики')
        self.geometry('820x700')
        self.minsize(640,520)
        self.parent=parent
        self.speaker=speaker
        self.brief=None
        self.project=None
        self.audience=None
        self.rendered_video=None
        self.running=False
        self.stop_event=threading.Event()
        self._notifications=queue.Queue()
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.topic=tk.StringVar(value='')
        self.country=tk.StringVar(value='RU')
        self.web_enabled=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='Сначала проанализируй статистику своего канала через CSV.')
        header=ttk.Frame(self,padding=12)
        header.pack(fill='x')
        ttk.Label(header,text='Тема (можно оставить пустой — предложу по результатам канала):').grid(row=0,column=0,sticky='w')
        ttk.Entry(header,textvariable=self.topic,width=60).grid(row=1,column=0,columnspan=3,sticky='ew',pady=6)
        ttk.Label(header,text='Тренды страны:').grid(row=2,column=0,sticky='w')
        ttk.Combobox(header,textvariable=self.country,values=['RU','DE','US','GB','UA','KZ'],width=7,state='readonly').grid(row=2,column=1,sticky='w')
        ttk.Checkbutton(header,text='Искать свежие тренды Google (передаётся только страна)',variable=self.web_enabled).grid(row=3,column=0,columnspan=3,sticky='w',pady=7)
        row=ttk.Frame(self,padding=(12,0,12,6))
        row.pack(fill='x')
        self.channel_button=ttk.Button(row,text='1. Изучить аудиторию (CSV)',command=self.import_channel)
        self.channel_button.pack(side='left',padx=(0,6))
        self.make_button=ttk.Button(row,text='2. Сценарий под аудиторию',command=self.generate)
        self.make_button.pack(side='left',padx=(0,6))
        self.load_button=ttk.Button(row,text='Открыть сценарий',command=self.open_brief)
        self.load_button.pack(side='left',padx=(0,6))
        self.speak_button=ttk.Button(row,text='Озвучить, что снимать',command=self.read_shots)
        self.speak_button.pack(side='left')
        second=ttk.Frame(self,padding=(12,0,12,8));second.pack(fill='x')
        self.edit_button=ttk.Button(second,text='3. Смонтировать мои кадры',command=self.montage)
        self.edit_button.pack(side='left',padx=(0,8))
        self.review_button=ttk.Button(second,text='4. Оценка готового ролика',command=self.review)
        self.review_button.pack(side='left',padx=(0,8))
        ttk.Button(second,text='Отменить текущую работу',command=self.cancel).pack(side='left')
        self.viewer=tk.Text(self,wrap='word',font=('Segoe UI',10))
        self.viewer.pack(fill='both',expand=True,padx=12,pady=(2,8))
        self.viewer.insert('end','JARVIS подготовит оригинальный сценарий и пронумерованный список кадров.\n'
                      'После съёмки положи видео в одну папку: 01.mp4, 02.mp4 и т. д.\n'
                      'Монтаж работает локально. Чужая музыка и чужие ролики не скачиваются.\n')
        self.viewer.configure(state='disabled')
        ttk.Label(self,textvariable=self.status,wraplength=690).pack(fill='x',padx=12,pady=(0,10))
        self.focus_set()
        self.after(100,self._pump_notifications)

    def _show(self, text):
        if not self.winfo_exists():return
        self.viewer.configure(state='normal')
        self.viewer.delete('1.0','end')
        self.viewer.insert('end',text)
        self.viewer.configure(state='disabled')

    def _busy(self, value):
        self.running=value
        state='disabled' if value else 'normal'
        for widget in (self.channel_button,self.make_button,self.edit_button,self.review_button,self.load_button):
            widget.configure(state=state)

    def _pump_notifications(self):
        if not self.winfo_exists():return
        try:
            while True:
                callback=self._notifications.get_nowait()
                if not self.parent._closing:callback()
        except queue.Empty:
            pass
        self.after(100,self._pump_notifications)

    def _notify(self,func):
        # Tk objects are touched exclusively by the main UI thread.
        self._notifications.put(func)

    def _spawn(self, worker):
        if self.running:return
        self.stop_event.clear()
        self._busy(True)
        def task():
            try:
                worker()
            except Exception as exc:
                detail=f'{type(exc).__name__}: {str(exc)[:400]}'
                self._notify(lambda: self.status.set('Ошибка: '+detail))
            finally:
                self._notify(lambda:self._busy(False))
        threading.Thread(target=task,daemon=True,name='jarvis-viral-studio').start()

    def _speak(self, text):
        if self.speaker and not self.parent._closing:
            threading.Thread(target=self.speaker.say,args=(text[:500],),daemon=True).start()

    def import_channel(self):
        csv_path=filedialog.askopenfilename(parent=self,
            title='Выбери экспорт своего канала из YouTube Studio',
            filetypes=[('Аналитика канала CSV','*.csv')])
        if not csv_path:return
        if not messagebox.askyesno('Разрешить чтение статистики',
            'Прочитать выбранный CSV только на этом компьютере? '
            'Пароль канала и видео не передаются.',parent=self):return
        self.status.set('Анализирую статистику канала…')
        topic_hint=self.topic.get().strip()
        def work():
            audience=analyze(import_csv(csv_path))
            try:topic=topic_hint or recommend_topic(audience)
            except ValueError:topic='Тема не выбрана'
            text=channel_report(audience)+'\n'+expert_report(audience,topic)
            def done():
                self.audience=audience
                if not self.topic.get().strip() and topic!='Тема не выбрана':
                    self.topic.set(topic)
                self._show(text)
                self.status.set(f'Изучено {len(audience.videos)} роликов. Теперь готов сценарий под интересы аудитории.')
            self._notify(done)
        self._spawn(work)

    def generate(self):
        if self.audience is None:
            messagebox.showwarning('Сначала статистика канала',
                'Импортируй свой CSV из YouTube Studio. Без этих данных нельзя знать, что нравится твоим зрителям.',
                parent=self)
            return
        topic=self.topic.get().strip()
        if not topic:
            try:topic=recommend_topic(self.audience)
            except ValueError:
                messagebox.showwarning('Тема','Укажи тему: в статистике нет повторяющихся интересов.',parent=self)
                return
        online=self.web_enabled.get()
        if online and not messagebox.askyesno('Разрешение на интернет',
            'Получить публичные поисковые тренды Google Trends по выбранной стране? '\
            'Видео, аудио и личные файлы не отправляются.',parent=self):return
        geo=self.country.get()
        self.status.set('Подбираю идею и сценарий…')
        def work():
            trends=[];note=''
            if online:
                try: trends=research_trends(geo=geo,consent=True)
                except Exception as exc:
                    note=f'Источник трендов недоступен ({str(exc)[:120]}). Будет сценарий без свежих трендов.\n'
            if self.stop_event.is_set():return
            try:
                brief=create_local_brief(topic,trends,audience=self.audience)
            except Exception as exc:
                note+=f'Локальная AI-модель сейчас недоступна ({str(exc)[:160]}). Используется подписанный шаблон.\n'
                brief=template_brief(topic,trends)
            if self.stop_event.is_set():return
            project=_home()/('video_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:6])
            save_brief(brief,project)
            (project/'AUDIENCE_EXPERTS_RU.md').write_text(
                channel_report(self.audience)+'\n'+expert_report(self.audience,topic),encoding='utf-8')
            text=note+f'Заголовок: {brief.title}\nЗацепка: {brief.hook}\n\nСценарий:\n{brief.script}\n\n'
            for i,shot in enumerate(brief.shots,1):
                text+=f'{i:02d}. [{shot.seconds:g} сек] {shot.film}\n   НА ЭКРАНЕ: {shot.caption}\n'
            text+=f'\nФинал: {brief.call_to_action}\n\nСоздано: {project}\nРежим: {brief.generator}\n'
            if trends:
                text+='\nТренды ПОИСКА (не вирусные видео):\n'+'\n'.join(t.title+' — '+t.traffic for t in trends)
            def done():
                self.brief=brief;self.project=project
                self._show(text)
                self.status.set('План готов. Отсними кадры 01.mp4, 02.mp4… и нажми «Смонтировать».')
                self._speak('Сценарий готов. Первый кадр: '+brief.shots[0].film)
            self._notify(done)
        self._spawn(work)

    def read_shots(self):
        if not self.brief:
            messagebox.showinfo('Сценарий','Сначала создай или открой сценарий.',parent=self);return
        # Speak ALL shots in sequence, rather than truncating the plan.
        shots=tuple(self.brief.shots)
        def speak_plan():
            for i,shot in enumerate(shots,1):
                if self.stop_event.is_set() or self.parent._closing:return
                if self.speaker:self.speaker.say(f'Кадр {i}. {shot.film}')
        threading.Thread(target=speak_plan,daemon=True,name='jarvis-viral-voice-guide').start()

    def open_brief(self):
        path=filedialog.askopenfilename(parent=self,title='Открыть brief.json',filetypes=[('JSON сценарий','*.json')])
        if not path:return
        try:
            brief=load_brief(Path(path));self.brief=brief;self.project=Path(path).parent
            self._show((self.project/'WHAT_TO_FILM_RU.md').read_text('utf-8') if (self.project/'WHAT_TO_FILM_RU.md').exists() else brief.script)
            self.status.set('Сценарий открыт. Можно приступать к монтажу.')
        except Exception as exc:messagebox.showerror('Ошибка',str(exc),parent=self)

    def montage(self):
        if not self.brief or not self.project:
            messagebox.showinfo('Нет сценария','Сначала подготовь сценарий.',parent=self);return
        folder=filedialog.askdirectory(parent=self,title='Выбери папку с твоими видео 01.mp4, 02.mp4 ...')
        if not folder:return
        if not messagebox.askyesno('Подтверждение монтажа',
            f'Собрать 9:16 MP4 из {len(self.brief.shots)} отснятых кадров в папке:\n{folder}\n\n'
            'Исходные файлы не будут изменены.',parent=self):return
        brief=self.brief
        project=self.project
        out=project/'JARVIS_NOVA_VERTICAL.mp4'
        self.status.set('Монтирую локально: кадрирование, склейка, экранные тексты…')
        def work():
            data=render_video(brief,Path(folder),out,cancel=self.stop_event)
            audience_review=None
            audit_text=''
            if not self.stop_event.is_set() and self.audience:
                try:
                    audience_review=assess_video(brief,self.audience,out)
                    report_file=store_assessment(audience_review,project)
                    audit_text=f'\n\nИтоговая оценка: {audience_review.index}/100 (это НЕ шанс вирусности).\nОтчёт: {report_file}'
                except Exception as exc:
                    audit_text='\n\nОценка пока не выполнена: '+str(exc)[:180]
            def done():
                self.rendered_video=out
                self.status.set('Ролик готов: '+str(out)+
                                (f' | соответствие аудитории: {audience_review.index}/100' if audience_review else ''))
                self._show('Готово!\n\nФайл: '+data['output']+'\n'
                           'Длительность: '+str(round(data['duration'],1))+' сек.\n'
                           'Соотношение: 9:16\n'
                           'Монтажный лист: '+str(out.with_name(out.stem+'_EDL.json'))+'\n\n'
                           'Проверь результат перед публикацией. JARVIS ничего не публикует автоматически.'+
                           audit_text)
                self._speak('Монтаж закончен. Ролик находится в папке проекта.')
            self._notify(done)
        self._spawn(work)

    def review(self):
        if not self.audience or not self.brief or not self.project:
            messagebox.showwarning('Нет анализа','Сначала импортируй статистику канала и смонтируй видео.',parent=self)
            return
        video=self.rendered_video or self.project/'JARVIS_NOVA_VERTICAL.mp4'
        if not video.is_file():
            messagebox.showwarning('Нет MP4','Сначала смонтируй ролик.',parent=self)
            return
        self.status.set('Проверяю реальный MP4 и его соответствие аудитории…')
        def work():
            assessment=assess_video(self.brief,self.audience,video)
            file=store_assessment(assessment,self.project)
            def done():
                self._show(file.read_text('utf-8'))
                self.status.set(f'Индекс соответствия: {assessment.index}/100. Это НЕ вероятность успеха.')
            self._notify(done)
        self._spawn(work)

    def cancel(self):
        self.stop_event.set()
        self.status.set('Запрошена отмена операции.')

    def close(self):
        self.cancel()
        self.destroy()
