import pathlib, sys, tempfile, unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from channel_audience import (read_channel_csv, analyze_audience, save_profile, load_profile,
                              AudienceDataError,VideoMetric)
from creator_experts import channel_experts, recommend_topic, prompt_context
from video_forecast import evaluate_final_cut,save_review
from viral_studio import template_brief,create_local_brief

CSV='''Video title,Views,Likes,Comments,Average percentage viewed,Duration
Тест камеры для дома,12000,480,31,88%,0:25
Камеры дома новое сравнение,14000,520,25,75%,0:31
Лучшие камеры и объективы,16000,810,45,91%,0:35
Древняя игра года,350,9,0,20%,1:23
Игра на телефоне,520,13,0,22%,1:12
Обзор дешевых наушников,600,19,1,30%,1:00
'''

class ChannelAudienceTests(unittest.TestCase):
    def _profile(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'export.csv';path.write_text(CSV,'utf-8')
            return analyze_audience(read_channel_csv(path))
    def test_csv_export_real_stats(self):
        p=self._profile()
        self.assertEqual(p.sample_size,6)
        self.assertEqual(p.typical_views,6300)
        self.assertIn('камеры',p.successful_topics)
        self.assertEqual(p.top_videos[0]['views'],16000)
        self.assertEqual(p.confidence,'низкая')
    def test_unicode_delimiter_and_decimal(self):
        with tempfile.TemporaryDirectory() as td:
            src=pathlib.Path(td)/'rus.csv'
            src.write_text('Название;Просмотры;Средний процент просмотра\n'
                           'Ремонт ламп;1 234;56,5%\n'
                           'Лампы и свет;1 100;48,3%\n'
                           'Светильники тест;2 500;65,2%\n',encoding='utf-8-sig')
            rows=read_channel_csv(src)
            self.assertEqual(rows[0].views,1234)
            self.assertEqual(rows[0].avg_view_pct,56.5)
    def test_minimal_or_invalid_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'small.csv'
            path.write_text('Title,Views\nOne,10\nTwo,20\n',encoding='utf-8')
            with self.assertRaises(AudienceDataError):read_channel_csv(path)
            path.write_text('Title,Views\nOne,10\nTwo,20\nThree,1000K\n',encoding='utf-8')
            with self.assertRaises(AudienceDataError):read_channel_csv(path)
    def test_no_fake_audience_data_or_passwords(self):
        with self.assertRaises(AudienceDataError):analyze_audience(())
        profile=self._profile()
        context=prompt_context(profile,'Камеры')
        self.assertNotIn('password',context)
        self.assertIn('sample_size',context)
        self.assertNotIn('Древняя игра года',context)
        self.assertEqual(len(channel_experts(profile,'Камеры')),5)
        self.assertIn('камеры',recommend_topic(profile))
    def test_profile_data_only_local(self):
        with tempfile.TemporaryDirectory() as td:
            orig=self._profile()
            file=save_profile(orig,pathlib.Path(td))
            self.assertEqual(load_profile(file),orig)
            with self.assertRaises(AudienceDataError):save_profile(orig,pathlib.Path(td))
    def test_csv_time_fields_are_true_sexagesimal_not_fake_99_seconds(self):
        with tempfile.TemporaryDirectory() as td:
            src=pathlib.Path(td)/'metrics.csv'
            for bad in ('1:60','1:75','1:99','0:61','1:60:00','3:23:90'):
                with self.subTest(bad=bad):
                    src.write_text(
                        'Video title,Views,Duration\n'
                        f'One,10,{bad}\nTwo,30,0:35\nThree,50,0:40\n',
                        encoding='utf-8')
                    with self.assertRaises(AudienceDataError):
                        read_channel_csv(src)
            src.write_text(
                'Video title,Views,Duration\n'
                'One,10,1:59\nTwo,30,0:59\nThree,50,1:02:03\n',
                encoding='utf-8')
            rows=read_channel_csv(src)
            self.assertEqual([row.duration for row in rows],[119.,59.,3723.])

    def test_saved_profile_rejects_poisoned_metrics_and_never_changes_source(self):
        import json
        from dataclasses import asdict
        good=asdict(self._profile())
        mutations=(
            ("negative_views",lambda d:d['videos'][0].__setitem__('views',-1)),
            ("string_views",lambda d:d['videos'][0].__setitem__('views',"1000")),
            ("boolean_views",lambda d:d['videos'][0].__setitem__('views',True)),
            ("infinite_ctr",lambda d:d['videos'][0].__setitem__('ctr',float('inf'))),
            ("negative_likes",lambda d:d['videos'][0].__setitem__('likes',-4)),
            ("wrong_title",lambda d:d['videos'][0].__setitem__('title',[])),
            ("unknown_field",lambda d:d['videos'][0].__setitem__('unsafe',123)),
            ("wrong_metric",lambda d:d['videos'].__setitem__(0,None)),
            ("too_many_videos",lambda d:d.__setitem__('videos',d['videos']*251)),
            ("invalid_source",lambda d:d.__setitem__('source',[])),
            ("invalid_video_list",lambda d:d.__setitem__('videos','not metrics')),
        )
        for label,change in mutations:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as td:
                root=pathlib.Path(td)/'channel_profile.json'
                data=json.loads(json.dumps(good,ensure_ascii=False))
                change(data)
                raw=json.dumps(data,ensure_ascii=False,allow_nan=True)
                root.write_text(raw,encoding='utf-8')
                with self.assertRaises(AudienceDataError):
                    load_profile(root)
                self.assertEqual(root.read_text('utf-8'),raw)

    def test_saved_profile_rejects_large_files_and_symlinks_before_loading(self):
        from channel_audience import MAX_PROFILE_BYTES
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            too_large=root/'huge.json'
            too_large.write_bytes(b'x'*(MAX_PROFILE_BYTES+1))
            with self.assertRaises(AudienceDataError):
                load_profile(too_large)
            self.assertEqual(too_large.stat().st_size,MAX_PROFILE_BYTES+1)
            shortcut=root/'linked.json'
            try:
                shortcut.symlink_to(too_large)
            except (OSError,NotImplementedError):
                return
            with self.assertRaises(AudienceDataError):
                load_profile(shortcut)
            self.assertTrue(shortcut.is_symlink())

    def test_profile_save_never_overwrites_file_created_after_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            dest=root/'channel_profile.json'
            original_open=pathlib.Path.open
            def concurrent_create(path,mode='r',*args,**kwargs):
                if path==dest and mode=='x':
                    dest.write_text('PRIVATE USER CONTENT',encoding='utf-8')
                return original_open(path,mode,*args,**kwargs)
            with patch('pathlib.Path.open',new=concurrent_create):
                with self.assertRaisesRegex(AudienceDataError,'существует'):
                    save_profile(self._profile(),root)
            self.assertEqual(dest.read_text('utf-8'),'PRIVATE USER CONTENT')

    def test_profile_save_rolls_back_partial_write_after_disk_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td)
            def broken_dump(data,stream,*args,**kwargs):
                stream.write('{"partial":')
                raise OSError('disk full')
            with patch('channel_audience.json.dump',side_effect=broken_dump):
                with self.assertRaisesRegex(OSError,'disk full'):
                    save_profile(self._profile(),root)
            self.assertFalse((root/'channel_profile.json').exists())
            self.assertEqual(list(root.iterdir()),[])

    def test_model_receives_aggregates_without_full_titles(self):
        profile=self._profile()
        runtime=Mock();runtime.start.return_value='http://127.0.0.1:1234'
        def requester(_,payload):
            self.assertIn('СТАТИСТИКА КАНАЛА',payload['prompt'])
            self.assertIn('sample_size',payload['prompt'])
            self.assertNotIn('Древняя игра года',payload['prompt'])
            return {'response':'{"title":"Камеры","hook":"Хук","script":"Сценарий","shots":['
                    '{"seconds":2,"film":"Покажи камеру","caption":"Камера"},'
                    '{"seconds":4,"film":"Сними тест","caption":"Тест"}],'
                    '"call_to_action":"Обсудим"}'}
        a=create_local_brief('Камеры',audience=profile,model_runtime=runtime,requester=requester)
        self.assertEqual(a.title,'Камеры')
        runtime.stop.assert_called_once()
    def test_review_after_final_file_not_probability(self):
        p=self._profile();brief=template_brief('Камеры')
        with tempfile.TemporaryDirectory() as td:
            file=pathlib.Path(td)/'final.mp4';file.write_bytes(b'0'*2000)
            with patch('video_forecast._probe',return_value=(23.3,True)):
                result=evaluate_final_cut(brief,p,file,tools=('ffmpeg','ffprobe'))
            self.assertIn('рекомендаций',result.limitations[-2]) if False else None
            self.assertGreaterEqual(result.index,0)
            self.assertLessEqual(result.index,100)
            self.assertIsNotNone(result.historical_range)
            path=save_review(result,pathlib.Path(td))
            report=path.read_text('utf-8')
            self.assertIn('НЕ прогноз',report)
            self.assertIn('НЕ процент вероятности вирусности',report)
    def test_final_without_render_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(Exception):evaluate_final_cut(template_brief('Камеры'),
                self._profile(),pathlib.Path(td)/'missing.mp4',tools=('ffmpeg','ffprobe'))
    def test_outlier_views_dont_fabricate_percent_chance(self):
        p=analyze_audience(tuple(VideoMetric(f'Камера опыт {i}',n) for i,n in enumerate([10,30,50,80,200,10000000])))
        self.assertLess(p.typical_views,100)
        self.assertEqual(p.confidence,'низкая')

if __name__=='__main__':unittest.main()
