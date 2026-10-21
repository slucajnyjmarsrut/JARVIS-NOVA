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
from online_media import search_free_video, download_free_video, OnlineMediaError
from editing_knowledge import read_ffmpeg_guide
from channel_audience import read_channel_csv, analyze_audience, AudienceDataError
from creator_experts import recommend_topic, expert_report
from video_forecast import evaluate_final_cut, save_review


def _home():
    # Data are preserved by Inno Setup upgrades/uninstalls.
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'JarvisNova' / 'viral_studio'


class ViralStudioWindow(tk.Toplevel):
    def __init__(self, parent, speaker=None):
        super().__init__(parent)
        self.title('JARVIS NOVA — Вирусные ролики')
        self.geometry('790x700')
        self.minsize(640,520)
        self.parent=parent
        self.speaker=speaker
        self.brief=None
        self.project=None
        self.profile=None
        self.rendered_video=None
        self.running=False
        self.stop_event=threading.Event()
        self._notifications=queue.Queue()
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.topic=tk.StringVar(value='')
        self.country=tk.StringVar(value='RU')
        self.web_enabled=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='Начни с экспорта статистики своего канала (CSV). Без анализа канала сценарий не создаётся.')
        header=ttk.Frame(self,padding=12)
        header.pack(fill='x')
        ttk.Label(header,text='Тема (можно оставить пустой: предложу из статистики канала):').grid(row=0,column=0,sticky='w')
        ttk.Entry(header,textvariable=self.topic,width=60).grid(row=1,column=0,columnspan=3,sticky='ew',pady=6)
        ttk.Label(header,text='Тренды страны:').grid(row=2,column=0,sticky='w')
        ttk.Combobox(header,textvariable=self.country,values=['RU','DE','US','GB','UA','KZ'],width=7,state='readonly').grid(row=2,column=1,sticky='w')
        ttk.Checkbutton(header,text='Искать свежие тренды Google (передаётся только страна)',variable=self.web_enabled).grid(row=3,column=0,columnspan=3,sticky='w',pady=7)
        row=ttk.Frame(self,padding=(12,0,12,6))
        row.pack(fill='x')
        self.audience_button=ttk.Button(row,text='1. Анализ аудитории канала (CSV)',command=self.import_audience)
        self.audience_button.pack(side='left',padx=(0,6))
        self.make_button=ttk.Button(row,text='2. Сценарий под аудиторию',command=self.generate)
        self.make_button.pack(side='left',padx=(0,6))
        self.load_button=ttk.Button(row,text='Открыть сценарий',command=self.open_brief)
        self.load_button.pack(side='left',padx=(0,6))
        self.speak_button=ttk.Button(row,text='Озвучить, что снимать',command=self.read_shots)
        self.speak_button.pack(side='left')
        second=ttk.Frame(self,padding=(12,0,12,8));second.pack(fill='x')
        self.edit_button=ttk.Button(second,text='3. Монтаж: мои или онлайн-кадры',command=self.montage)
        self.edit_button.pack(side='left',padx=(0,8))
        self.review_button=ttk.Button(second,text='4. Оценить для аудитории',command=self.review)
        self.review_button.pack(side='left',padx=(0,8))
        ttk.Button(second,text='Отменить текущую работу',command=self.cancel).pack(side='left')
        guide_row=ttk.Frame(self,padding=(12,0,12,6))
        guide_row.pack(fill='x')
        ttk.Button(guide_row,text='Изучить официальную справку FFmpeg',
                   command=self.study_editing).pack(side='left')
        self.viewer=tk.Text(self,wrap='word',font=('Segoe UI',10))
        self.viewer.pack(fill='both',expand=True,padx=12,pady=(2,8))
        self.viewer.insert('end','JARVIS подготовит оригинальный сценарий и пронумерованный список кадров.\n'
                      'После съёмки положи видео в одну папку: 01.mp4, 02.mp4 и т. д.\n'
                      'Монтаж работает локально. Онлайн-поиск видео доступен только после разрешения.\n')
        self.viewer.configure(state='disabled')
        ttk.Label(self,textvariable=self.status,wraplength=690).pack(fill='x',padx=12,pady=(0,10))
        self.focus_set()
        self.after(100,self._pump_notifications)

    def focus_stage(self, stage: str):
        """Navigate without triggering filesystem dialogs, web requests or rendering."""
        descriptions={
            'audience':('1. Анализ аудитории: импортируй свою статистику CSV.',self.audience_button),
            'script':('2. Сценарий: сначала нужен анализ аудитории канала.',self.make_button),
            'shoot':('3. Съёмка: открой сценарий и озвучь список кадров.',self.speak_button),
            'edit':('4. Монтаж: выбери отснятые кадры и подтверди обработку.',self.edit_button),
            'review':('5. Оценка: проверь готовый MP4 относительно данных аудитории.',self.review_button),
        }
        message,button=descriptions.get(stage,descriptions['audience'])
        self.status.set(message)
        try:button.focus_set()
        except tk.TclError:pass

    def _show(self, text):
        if not self.winfo_exists():return
        self.viewer.configure(state='normal')
        self.viewer.delete('1.0','end')
        self.viewer.insert('end',text)
        self.viewer.configure(state='disabled')

    def _busy(self, value):
        self.running=value
        state='disabled' if value else 'normal'
        for widget in (self.make_button,self.edit_button,self.load_button,self.audience_button,self.review_button):
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

    def import_audience(self):
        path=filedialog.askopenfilename(parent=self,title='Выбери экспорт статистики своего канала',
                                        filetypes=[('Экспорт CSV','*.csv')])
        if not path:return
        if not messagebox.askyesno('Доступ к аналитике',
            'Прочитать ВЫБРАННЫЙ CSV локально, определить любимые темы зрителей и формат? '
            'Пароли и видеозаписи не передаются. Отчёт остаётся на ПК.',parent=self):return
        self.status.set('Анализирую реальные просмотры, темы и удержание…')
        requested_topic=self.topic.get().strip()
        def work():
            videos=read_channel_csv(Path(path))
            profile=analyze_audience(videos,source='CSV из папки пользователя')
            try: topic=requested_topic or recommend_topic(profile)
            except ValueError:topic='Тема будет выбрана вручную'
            report=expert_report(profile,topic)
            def done():
                self.profile=profile
                if not self.topic.get().strip() and topic!='Тема будет выбрана вручную':
                    self.topic.set(topic)
                self._show(report)
                self.status.set('Аудитория изучена: '+str(profile.sample_size)+
                                ' роликов. Можно создавать сценарий.')
                self._speak('Я изучил показатели канала. Теперь предложу, что снимать для этой аудитории.')
            self._notify(done)
        self._spawn(work)

    def generate(self):
        if self.profile is None:
            messagebox.showwarning('Сначала аудитория',
                'Сначала импортируй статистику своего канала (CSV), чтобы сценарий опирался на реальных зрителей.',
                parent=self)
            return
        topic=self.topic.get().strip()
        if not topic:
            try:topic=recommend_topic(self.profile)
            except ValueError:
                messagebox.showwarning('Тема','Статистика не выявила повторяющейся темы. Напиши свою.',parent=self)
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
                brief=create_local_brief(topic,trends,audience=self.profile)
            except Exception as exc:
                note+=f'Локальная AI-модель сейчас недоступна ({str(exc)[:160]}). Используется подписанный шаблон.\n'
                brief=template_brief(topic,trends)
            if self.stop_event.is_set():return
            project=_home()/('video_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:6])
            save_brief(brief,project)
            (project/'AUDIENCE_EXPERTS_RU.md').write_text(expert_report(self.profile,topic),encoding='utf-8')
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

    def study_editing(self):
        if not messagebox.askyesno('Разрешить справку FFmpeg',
                'Загрузить только публичную официальную документацию с ffmpeg.org? '
                'Никакие команды с сайта не выполняются и модели не переобучаются.',
                parent=self):
            return
        self.status.set('Читаю официальную документацию FFmpeg…')
        def work():
            reference=read_ffmpeg_guide(consent=True)
            def done():
                self._show(reference)
                self.status.set('Справка получена. Это справочная информация, не изменение алгоритмов.')
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
        online=messagebox.askyesno('Источник видео',
            'Искать открытые видеоклипы на Wikimedia Commons?\n\n'
            'Будет передана только тема ролика. Сохраняются ссылки на '
            'источники и условия CC0, Public Domain или CC BY. '
            'Авторство и применимость лицензии проверь до публикации.\n\n'
            'Нет — выбрать собственные видео.',parent=self)
        folder=None
        if not online:
            folder=filedialog.askdirectory(parent=self,title='Выбери папку с клипами 01.mp4, 02.mp4 ...')
            if not folder:return
            if not messagebox.askyesno('Подтверждение монтажа',
                f'Смонтировать {len(self.brief.shots)} кадров из {folder}? '
                'Исходные файлы не изменятся.',parent=self):return
        brief=self.brief
        project=self.project
        out=project/'JARVIS_NOVA_VERTICAL.mp4'
        self.status.set('Ищу открытые материалы…' if online else
                        'Монтирую локально: кадрирование, склейка, экранные тексты…')
        def work():
            source=Path(folder) if folder is not None else None
            credits=''
            if online:
                candidates=search_free_video(brief.topic,consent=True)
                if len(candidates)<len(brief.shots):
                    raise OnlineMediaError(
                        f'По теме «{brief.topic}» найдено {len(candidates)} клипов, '
                        f'нужно {len(brief.shots)}. Уточни тему или выбери свою папку.')
                source=project/('online_clips_'+uuid4().hex[:8])
                download_free_video(candidates[:len(brief.shots)],source,
                                    consent=True,cancel=self.stop_event)
                credits=str(source/'CREDITS_RU.md')
            if self.stop_event.is_set():return
            data=render_video(brief,source,out,cancel=self.stop_event)
            review=None; report=None
            if self.profile is not None and not self.stop_event.is_set():
                try:
                    review=evaluate_final_cut(brief,self.profile,out,rendered=data)
                    report=save_review(review,project)
                except Exception as exc:
                    # Do not claim a successful audience review when ffprobe fails.
                    report='Итоговая оценка не получена: '+str(exc)[:150]
            def done():
                self.rendered_video=out

                self.status.set('Ролик готов: '+str(out)+
                                (f' | оценка {review.index}/100 (НЕ вероятность вирусности)' if review else
                                 ' | оценка недоступна'))
                self._show('Готово!\n\nФайл: '+data['output']+'\n'
                           'Длительность: '+str(round(data['duration'],1))+' сек.\n'
                           'Соотношение: 9:16\n'
                           'Лицензии и авторство: '+credits+'\\n'
                           'Монтажный лист: '+str(out.with_name(out.stem+'_EDL.json'))+'\n'
                           'Аудитория и потенциал: '+str(report)+'\n\n'
                           'Проверь результат перед публикацией. JARVIS ничего не публикует автоматически.')
                self._speak('Монтаж закончен. Ролик находится в папке проекта.')
            self._notify(done)
        self._spawn(work)

    def review(self):
        if not self.profile or not self.brief or not self.project:
            messagebox.showwarning('Нет данных','Сначала проанализируй канал и подготовь ролик.',parent=self)
            return
        out=self.rendered_video or self.project/'JARVIS_NOVA_VERTICAL.mp4'
        if not out.is_file():
            messagebox.showwarning('Нет ролика','Сначала смонтируй видео.',parent=self);return
        self.status.set('Проверяю готовый MP4 и соответствие аудитории…')
        def work():
            review=evaluate_final_cut(self.brief,self.profile,out)
            file=save_review(review,self.project)
            def done():
                self._show(file.read_text('utf-8'))
                self.status.set('Индекс соответствия: '+str(review.index)+'/100. Это НЕ вероятность популярности.')
                self._speak('Оценка закончена. Это индекс соответствия каналу, а не гарантия просмотров.')
            self._notify(done)
        self._spawn(work)

    def cancel(self):
        self.stop_event.set()
        self.status.set('Запрошена отмена операции.')

    def close(self):
        self.cancel()
        self.destroy()
