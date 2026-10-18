# -*- coding: utf-8 -*-
"""Grounded audience analysis and final edited-MP4 review; no internet or credentials."""
import pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from channel_audience import import_csv,analyze,recommend_topic,AudienceDataError,audience_context
from creator_experts import consult_experts
from video_forecast import assess_video,store_assessment
from viral_studio import template_brief,create_local_brief,ViralStudioError

EXPORT='''Video title,Views,Likes,Comments,Average percentage viewed
Камеры для дома,12000,480,31,75%
Камеры и объективы,14000,520,25,88%
Сравнение камер,16000,810,45,91%
Компьютерные игры,350,9,0,20%
Игры на телефоне,520,13,0,22%
Наушники и звук,600,19,1,30%
'''

class AudiencePipelineTests(unittest.TestCase):
    def profile(self):
        with tempfile.TemporaryDirectory() as folder:
            f=pathlib.Path(folder)/'channel.csv';f.write_text(EXPORT,encoding='utf-8')
            return analyze(import_csv(f))
    def test_real_metrics_and_winning_topic(self):
        p=self.profile()
        self.assertEqual(len(p.videos),6)
        self.assertEqual(p.typical_views,6300)
        self.assertIn('камеры',p.winning_topics)
        self.assertEqual(p.confidence,'низкая')
    def test_experts_dont_pretend_to_be_real_people(self):
        p=self.profile()
        self.assertEqual(len(consult_experts(p,'Камеры')),5)
        self.assertTrue(recommend_topic(p))
    def test_bad_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            f=pathlib.Path(folder)/'channel.csv';f.write_text('Title,Views\nOne,1\nTwo,2\n',encoding='utf-8')
            with self.assertRaises(AudienceDataError):import_csv(f)
            f.write_text('Title,Views\nOne,1\nTwo,2\nThree,10K\n',encoding='utf-8')
            with self.assertRaises(AudienceDataError):import_csv(f)
    def test_local_ai_only_receives_aggregate(self):
        p=self.profile()
        text=audience_context(p)
        self.assertNotIn('Наушники и звук',text)
        runtime=Mock();runtime.start.return_value='http://127.0.0.1:1234'
        def request(url,payload):
            self.assertIn('ДАННЫЕ КАНАЛА',payload['prompt'])
            self.assertNotIn('Наушники и звук',payload['prompt'])
            return {'response':'{"title":"Тест","hook":"Первый кадр","script":"Рассказ",'
                    '"shots":[{"seconds":2,"film":"Камера","caption":"Начало"},'
                    '{"seconds":5,"film":"Сравнить","caption":"Результат"}],'
                    '"call_to_action":"Обсудим"}'}
        result=create_local_brief('Камеры',audience=p,model_runtime=runtime,requester=request)
        self.assertEqual(result.title,'Тест')
        runtime.stop.assert_called_once()
    def test_only_actual_mp4_can_be_assessed(self):
        p=self.profile()
        with tempfile.TemporaryDirectory() as folder:
            f=pathlib.Path(folder)/'final.mp4'
            with self.assertRaises(ViralStudioError):
                assess_video(template_brief('Камеры'),p,f,tools=('ffmpeg','ffprobe'))
            f.write_bytes(b'0'*1500)
            with patch('video_forecast._probe',return_value=(23.0,True)):
                review=assess_video(template_brief('Камеры'),p,f,tools=('ffmpeg','ffprobe'))
            self.assertTrue(0<=review.index<=100)
            self.assertIsNotNone(review.historical_views)
            report=store_assessment(review,pathlib.Path(folder)).read_text(encoding='utf-8')
            self.assertIn('НЕ ПРОГНОЗ',report)
            self.assertIn('НЕ является шансом вирусности',report)

if __name__=='__main__':unittest.main()
