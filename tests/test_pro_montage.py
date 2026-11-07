# -*- coding: utf-8 -*-
"""Pro montage unit and true FFmpeg tests: no models or network required."""
import math
import shutil
import struct
import tempfile
import unittest
import subprocess
import json
from pathlib import Path
from pro_montage import (ProOptions,validate_options,color_filter,title_filters,
                         detect_beats,snap_length,semantic_highlight_start,finish_video)
FFMPEG=shutil.which('ffmpeg')
FFPROBE=shutil.which('ffprobe')

def run(argv,*,timeout=60,cancel=None):
    task=subprocess.run(argv,capture_output=True,timeout=timeout)
    if task.returncode:raise RuntimeError(task.stderr.decode(errors='replace')[-1200:])
    return task.stdout

class ProMontageTests(unittest.TestCase):
    def test_validate_bad_options(self):
        for values in (dict(transition=-.1),dict(transition=.8),
                       dict(color='evil'),dict(music_volume=1.),
                       dict(semantic=1)):
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate_options(ProOptions(**values))
    def test_colors_titles(self):
        self.assertIn('eq=',color_filter('natural'))
        self.assertEqual(color_filter('none'),'')
        self.assertIn('fade=t=in',title_filters(1.5,True)[0])
        self.assertEqual(title_filters(1.5,False),('', '1:v:0'))
    def test_beats_and_snap(self):
        samples=[0]*40000
        for sec in (1,2,3,4):
            start=sec*8000
            for k in range(start,start+800):samples[k]=12000 if k%2 else -12000
        raw=struct.pack('<'+'h'*len(samples),*samples)
        beats=detect_beats(raw)
        self.assertTrue(any(abs(b-2)<.11 for b in beats),beats)
        self.assertAlmostEqual(snap_length(2.04,0,beats,overlap=.2,maximum=2.3),2.1,delta=.11)
        self.assertEqual(detect_beats(b'\x00'*16000),[])
    def test_semantic_fallback_and_local_scoring(self):
        jpeg=b'\xff\xd8\xff'+b'x'*1100+b'\xff\xd9'
        i=[0]
        def describe(question,frame):
            i[0]+=1
            return ['2','9','3'][i[0]-1]
        best,meta=semantic_highlight_start(Path('example.mp4'),8,2,'город',
                        FFMPEG or 'ffmpeg',describe=describe,
                        executor=lambda *a,**kw:jpeg)
        self.assertEqual(meta['mode'],'local_vision')
        self.assertAlmostEqual(best,2.96,delta=.2)
        fallback,why=semantic_highlight_start(Path('example.mp4'),8,2,'город',
                        FFMPEG or 'ffmpeg',describe=None,executor=lambda *a,**kw:jpeg,
                        fallback=.7)
        self.assertEqual(fallback,.7)
        self.assertEqual(why['mode'],'pixel')
    @unittest.skipUnless(FFMPEG and FFPROBE,'FFmpeg not installed')
    def test_real_video_transitions_and_music(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            for i,color in enumerate(('red','green','blue')):
                run([FFMPEG,'-v','error','-y','-f','lavfi','-i',
                    f'color=c={color}:s=180x320:r=30:d=1.5',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1.5',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',
                    '-shortest',str(d/f'{i}.mp4')])
            run([FFMPEG,'-v','error','-y','-f','lavfi','-i',
                 'sine=frequency=200:sample_rate=48000:duration=6',
                 '-c:a','aac',str(d/'sound.m4a')])
            out=d/'result.mp4'
            result=finish_video([d/f'{i}.mp4' for i in range(3)],
                 [1.5]*3,out,FFMPEG,options=ProOptions(transition=.25,
                 music_path=d/'sound.m4a'),executor=run)
            info=json.loads(run([FFPROBE,'-v','error','-show_format',
                                 '-show_streams','-of','json',str(out)]))
            self.assertAlmostEqual(float(info['format']['duration']),4.,delta=.2)
            self.assertEqual(result['music_used'],True)
            self.assertTrue(any(s['codec_name']=='h264' for s in info['streams']))
            self.assertTrue(any(s['codec_name']=='aac' for s in info['streams']))
    @unittest.skipUnless(FFMPEG and FFPROBE,'FFmpeg not installed')
    def test_hard_cut_without_music(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            for i in range(2):
                run([FFMPEG,'-v','error','-y','-f','lavfi','-i',
                     'color=c=blue:s=180x320:r=30:d=1',
                     '-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
                     '-t','1','-c:v','libx264','-pix_fmt','yuv420p',
                     '-c:a','aac',str(d/f'{i}.mp4')])
            out=d/'result.mp4'
            finish_video([d/'0.mp4',d/'1.mp4'],[1.,1.],out,FFMPEG,
                         options=ProOptions(transition=0),executor=run)
            info=json.loads(run([FFPROBE,'-v','error','-show_format','-of','json',str(out)]))
            self.assertAlmostEqual(float(info['format']['duration']),2.,delta=.2)
if __name__=='__main__':unittest.main()
