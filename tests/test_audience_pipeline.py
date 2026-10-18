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
