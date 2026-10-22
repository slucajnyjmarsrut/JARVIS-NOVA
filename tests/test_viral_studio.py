# -*- coding: utf-8 -*-
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from viral_studio import (Trend, Shot, Brief, ViralStudioError, research_trends,
                          template_brief, save_brief, load_brief, create_local_brief,
                          render_video, ffmpeg_tools)

RSS='''<?xml version="1.0" encoding="UTF-8"?><rss xmlns:ht="https://trends.google.com/trending/rss">
<channel><item><title>Камеры</title><ht:approx_traffic>5000+</ht:approx_traffic><pubDate>Sun, 18 Oct 2026 06:00 GMT</pubDate><link>https://evil.example</link></item></channel></rss>'''.encode()

class ViralTests(unittest.TestCase):
    def test_network_requires_permission(self):
        with self.assertRaises(PermissionError):research_trends(transport=lambda _:RSS)
    def test_real_rss_parsing_no_untrusted_url(self):
        trends=research_trends(geo='RU',consent=True,transport=lambda _:RSS)
        self.assertEqual(trends[0].title,'Камеры')
        self.assertEqual(trends[0].traffic,'5000+')
        self.assertEqual(trends[0].source_url,'https://trends.google.com/trending?geo=RU')
    def test_country_rejects_url_injection(self):
        with self.assertRaises(ValueError):research_trends(geo='../US',consent=True,transport=lambda _:RSS)
    def test_xml_entities_rejected(self):
        with self.assertRaises(ViralStudioError):
            research_trends(consent=True,transport=lambda _:b'<!DOCTYPE x [<!ENTITY boom "x">]><rss/>')
    def test_template_is_marked_not_ai(self):
        result=template_brief('Кофе')
        self.assertIn('шаблон',result.generator)
        self.assertEqual(len(result.shots),5)
    def test_brief_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            b=template_brief('Игры', [Trend('новый тренд','','','https://trends.google.com/trending?geo=RU')])
            filename=save_brief(b,pathlib.Path(temp))
            self.assertEqual(load_brief(filename),b)
            self.assertIn('Что снять',(pathlib.Path(temp)/'WHAT_TO_FILM_RU.md').read_text('utf-8'))
            with self.assertRaises(ViralStudioError):save_brief(b,pathlib.Path(temp))
    def test_ai_json_and_child_shutdown(self):
        runtime=Mock();runtime.start.return_value='http://127.0.0.1:1234'
        mock_response={'title':'Тест','hook':'Смотри!','script':'Сегодня показываю новый трюк.',
            'shots':[{'seconds':3,'film':'Снять вопрос крупным планом','caption':'Неожиданно!'},
                     {'seconds':5,'film':'Показать ответ камерой','caption':'Вот как'}],
            'call_to_action':'Подписывайся'}
        def requester(url, payload):
            self.assertEqual(url,'http://127.0.0.1:1234/api/generate')
            self.assertEqual(payload['model'],'qwen3-vl:2b-instruct')
            return {'response':json.dumps(mock_response,ensure_ascii=False)}
        b=create_local_brief('Камеры',model_runtime=runtime,requester=requester)
        self.assertIn('Qwen3',b.generator)
        runtime.stop.assert_called_once()
    def test_ai_failure_stops_process(self):
        runtime=Mock();runtime.start.return_value='http://127.0.0.1:1234'
        with self.assertRaises(ViralStudioError):
            create_local_brief('Камеры',model_runtime=runtime,requester=lambda a,b: {'response':'not json'})
        runtime.stop.assert_called_once()
    def test_missing_footage_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ViralStudioError):render_video(template_brief('Зима'),pathlib.Path(temp),pathlib.Path(temp)/'output.mp4')
    def test_refuse_output_in_footage_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            footage=pathlib.Path(temp)/'raw';footage.mkdir()
            for i in range(5):(footage/f'{i}.mp4').write_bytes(b'fake')
            with self.assertRaises(ViralStudioError):render_video(template_brief('Кофе'),footage,footage/'output.mp4')
    def test_existing_edit_decisions_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)
            clips=root/'raw'
            clips.mkdir()
            for i in range(5):
                (clips/f'{i:02}.mp4').write_bytes(b'bad media')
            output=root/'ready.mp4'
            metadata=root/'ready_EDL.json'
            metadata.write_text('USER FILE: DO NOT CHANGE',encoding='utf-8')
            with self.assertRaisesRegex(ViralStudioError,'существ'):
                render_video(template_brief('Книги'),clips,output)
            self.assertEqual(metadata.read_text('utf-8'),'USER FILE: DO NOT CHANGE')
            self.assertFalse(output.exists())

    def test_publishing_failure_rolls_back_partial_video_and_sidecars(self):
        try:
            ffmpeg,ffprobe=ffmpeg_tools()
        except ViralStudioError:
            self.skipTest('FFmpeg not installed on this runner')
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)
            clips=root/'raw';clips.mkdir()
            for i in range(2):
                subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','color=c=blue:s=180x320:r=12:d=1.6',
                    '-c:v','libx264','-pix_fmt','yuv420p',
                    str(clips/f'{i+1:02}.mp4')],check=True,capture_output=True)
            shot=Shot(1.,'Снимок','Тест')
            brief=Brief('Тест','Синий','Хук','Сюжет',(shot,shot),'Финал','шаблон')
            out=root/'export'/'video.mp4'
            calls=[]
            original=shutil.copyfileobj
            def faulty_copy(src,dst,**kwargs):
                calls.append(dst.name)
                if len(calls)==2:
                    dst.write(b'PARTIAL')
                    raise OSError('simulated interrupted metadata write')
                return original(src,dst,**kwargs)
            with patch('viral_studio.shutil.copyfileobj',side_effect=faulty_copy):
                with self.assertRaisesRegex(OSError,'interrupted'):
                    render_video(brief,clips,out,size=(180,320),tools=(ffmpeg,ffprobe))
            self.assertFalse(out.exists())
            self.assertFalse(out.with_suffix('.srt').exists())
            self.assertFalse(out.with_name('video_EDL.json').exists())
            self.assertTrue((clips/'01.mp4').exists())

    def test_render_real_ffmpeg_clip_to_mp4(self):
        try: ffmpeg,ffprobe=ffmpeg_tools()
        except ViralStudioError: self.skipTest('FFmpeg not installed on this runner')
        with tempfile.TemporaryDirectory() as temp:
            raw=pathlib.Path(temp)/'raw';raw.mkdir()
            for i,color in enumerate(('red','blue'),1):
                cmd=[ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi',
                     '-i',f'color=c={color}:s=240x320:r=12:d=1.5','-c:v','libx264',
                     '-pix_fmt','yuv420p',str(raw/f'{i:02}.mp4')]
                subprocess.run(cmd,check=True,capture_output=True)
            b=Brief('Пример','Проба','Хук','Сцена 1. Сцена 2.',
                    (Shot(1,'Первый кадр','Проверка'),Shot(1,'Второй кадр','Результат')),
                    'Финал','шаблон')
            output=pathlib.Path(temp)/'result'/'final.mp4'
            meta=render_video(b,raw,output,size=(180,320),tools=(ffmpeg,ffprobe))
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size,2000)
            self.assertEqual(len(meta['segments']),2)
            self.assertTrue(output.with_name('final_EDL.json').exists())
            self.assertTrue(output.with_suffix('.srt').exists())
            self.assertIn('00:00:00,000 -->',output.with_suffix('.srt').read_text('utf-8-sig'))
            self.assertTrue(meta['technical_quality']['quality_checked'])
            self.assertEqual(meta['technical_quality']['video_codec'],'h264')
            self.assertEqual(meta['technical_quality']['audio_codec'],'aac')
            self.assertTrue((raw/'01.mp4').exists())
    def test_cancel_preempts_render(self):
        with tempfile.TemporaryDirectory() as temp:
            clips=pathlib.Path(temp)/'raw';clips.mkdir()
            for i in range(5):(clips/f'{i}.mp4').write_bytes(b'fake')
            canceled=threading.Event();canceled.set()
            with self.assertRaises(ViralStudioError):
                render_video(template_brief('Книги'),clips,pathlib.Path(temp)/'final.mp4',cancel=canceled)

if __name__=='__main__':unittest.main()
