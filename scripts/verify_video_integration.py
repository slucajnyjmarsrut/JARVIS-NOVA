# -*- coding: utf-8 -*-
"""Offline FFmpeg integration smoke with synthetic, locally created footage.

If executed in a *full JARVIS checkout*, test the existing viral_studio.render_video
rather than a mock. This uses tiny original test patterns, no uploaded videos.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(args,timeout=50):
    return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          timeout=timeout,shell=False)


def verify_video(repo: Path|None=None):
    ffmpeg=shutil.which('ffmpeg')
    ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        return {'status':'skipped','reason':'FFmpeg и ffprobe не установлены'}
    with tempfile.TemporaryDirectory(prefix='jarvis-video-smoke-') as tmp:
        folder=Path(tmp)
        clips=folder/'footage'
        clips.mkdir()
        for n in (1,2):
            run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                 '-f','lavfi','-i',f'testsrc2=size=320x568:rate=30',
                 '-f','lavfi','-i',f'sine=frequency={440+n*100}:sample_rate=48000',
                 '-t','2.2','-c:v','libx264','-preset','ultrafast',
                 '-pix_fmt','yuv420p','-c:a','aac','-b:a','64k','-shortest',
                 str(clips/f'{n:02}.mp4')],timeout=40)
        out=folder/'result'/'check.mp4'
        if repo is not None:
            repo=Path(repo).resolve()
            if (repo/'viral_studio.py').is_file() and (repo/'smart_montage.py').is_file():
                sys.path.insert(0,str(repo))
                from viral_studio import Brief, Shot, render_video
                brief=Brief('Тест монтажа','Тест','Пример','Проверка синтетических клипов',
                            (Shot(1.1,'Первая сцена','Первый кадр'),
                             Shot(1.1,'Вторая сцена','Второй кадр')),
                            'Готово','локальная проверка')
                result=render_video(brief,clips,out,size=(180,320),tools=(ffmpeg,ffprobe))
                if not out.with_suffix('.srt').is_file():
                    raise AssertionError('После рендера нет SRT')
                if not out.with_name('check_EDL.json').is_file():
                    raise AssertionError('После рендера нет монтажного листа')
                engine='viral_studio.render_video'
            else:
                raise FileNotFoundError('В указанной папке нет полного видеоредактора JARVIS')
        else:
            # Standalone FFmpeg environment check, NOT proof of viral_studio compatibility.
            playlist=folder/'playlist.txt'
            playlist.write_text("file 'footage/01.mp4'\nfile 'footage/02.mp4'\n",encoding='utf-8')
            out.parent.mkdir()
            run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                 '-f','concat','-safe','0','-i',str(playlist),'-c','copy',str(out)],timeout=40)
            engine='ffmpeg-only (not a JARVIS integration test)'
        metadata=json.loads(run([ffprobe,'-v','error','-show_format','-show_streams',
                                 '-of','json',str(out)]).stdout)
        video=next(s for s in metadata['streams'] if s['codec_type']=='video')
        audio=next(s for s in metadata['streams'] if s['codec_type']=='audio')
        assert video['codec_name']=='h264' and audio['codec_name']=='aac'
        assert int(video['width']) < int(video['height'])
        assert float(metadata['format']['duration'])>1.9
        assert out.stat().st_size>1000
        return {'status':'passed','engine':engine,'video_codec':'h264','audio_codec':'aac',
                'duration':round(float(metadata['format']['duration']),2),
                'vertical':True,'size_bytes':out.stat().st_size}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=None,help='Full local JARVIS checkout')
    options=parser.parse_args()
    print(json.dumps(verify_video(options.repo),ensure_ascii=False,indent=2))
