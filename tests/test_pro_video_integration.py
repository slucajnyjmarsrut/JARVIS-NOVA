# -*- coding: utf-8 -*-
"""End-to-end pro video export with real FFmpeg and no external model service."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pro_montage import ProOptions
from viral_studio import Brief, Shot, render_video, ffmpeg_tools, ViralStudioError


class ProRenderIntegration(unittest.TestCase):
    def test_transitions_beat_music_semantic_and_srt(self):
        try:
            ffmpeg, ffprobe=ffmpeg_tools()
        except ViralStudioError:
            self.skipTest('ffmpeg and ffprobe unavailable')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            clips=root/'footage'
            clips.mkdir()
            for i,color in enumerate(('red','blue'),1):
                subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i',f'color=c={color}:s=180x320:r=30:d=3.2',
                    '-f','lavfi','-i','sine=frequency=330:sample_rate=48000:duration=3.2',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',
                    '-shortest',str(clips/f'{i:02}.mp4')],capture_output=True,check=True,timeout=45)
            music=root/'owned.m4a'
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=5',
                '-c:a','aac',str(music)],capture_output=True,check=True,timeout=20)
            brief=Brief('Город','Улица','Старт','Две сцены',
                (Shot(1.4,'Покажи красный объект','Первый титр'),
                 Shot(1.4,'Покажи синий объект','Второй титр')),
                'Финал','шаблон')
            out=root/'export'/'pro.mp4'
            result=render_video(brief,clips,out,size=(180,320),
                tools=(ffmpeg,ffprobe),
                pro_options=ProOptions(music_path=music,semantic=True),
                semantic_describe=lambda question,jpeg:'8')
            self.assertTrue(out.is_file())
            self.assertTrue(result['technical_quality']['quality_checked'])
            self.assertEqual(result['professional']['music_used'],True)
            self.assertEqual(result['professional']['transition'],'fade')
            self.assertTrue(result['professional']['animated_screen_titles'])
            self.assertEqual(result['segments'][0]['selection']['mode'],'local_vision')
            expected=sum(s['seconds'] for s in result['segments'])-.22
            self.assertAlmostEqual(result['duration'],expected,delta=.35)
            subtitle=out.with_suffix('.srt').read_text(encoding='utf-8-sig')
            self.assertIn('Первый титр',subtitle)
            self.assertIn('Второй титр',subtitle)
            edl=json.loads(out.with_name('pro_EDL.json').read_text(encoding='utf-8'))
            self.assertIn('professional',edl)
            self.assertTrue(edl['professional']['music_used'])
            self.assertTrue((clips/'01.mp4').exists())
            with self.assertRaisesRegex(ViralStudioError,'существ'):
                render_video(brief,clips,out,size=(180,320),
                    tools=(ffmpeg,ffprobe),pro_options=ProOptions())
if __name__=='__main__':
    unittest.main()
