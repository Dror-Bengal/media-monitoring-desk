import json
import os
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline.analysis import classify
from pipeline.demo import fixture_services, ROOT
from pipeline.models import Article
from pipeline.worker import cycle, open_db

class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"monitor.db"
        self.db = open_db(self.path)
        self.addCleanup(lambda:self.db.close())
        self.rules = json.loads((ROOT/"examples/watchlist.json").read_text())
        self.now = int(datetime(2026,1,2,18,15,tzinfo=timezone.utc).timestamp())

    def test_two_destinations_and_no_resend_after_restart(self):
        with fixture_services() as (sources,channels,accepted,_):
            out = cycle(self.db,sources,self.rules,"rules",channels,self.now)
            self.assertEqual(out,{"fetched":5,"analysis_errors":0,"delivery_errors":0})
            self.assertCountEqual([c for c,_ in accepted],["telegram","whatsapp"])
            text = dict(accepted)["telegram"]
            self.assertEqual(text,dict(accepted)["whatsapp"])
            self.assertIn("Sources: City Clerk, Harbour Desk",text)
            self.assertIn("North Hall at 18:00",text)
            self.assertTrue(text.endswith("https://notices.example/waterfront-update"))
            self.assertEqual(dict(self.db.execute("SELECT tier,count(*) FROM articles GROUP BY tier")),
                             {"CRITICAL":2,"HIGH":1,"MEDIUM":1,"SKIP":1})
            self.db.close()
            self.db = open_db(self.path)
            cycle(self.db,sources,self.rules,"rules",channels,self.now+30)
            self.assertEqual(len(accepted),2)

    def test_failed_channel_retries_independently_without_new_articles(self):
        for failing in ("telegram","whatsapp"):
            with self.subTest(channel=failing), fixture_services() as (sources,channels,accepted,reject):
                # Isolate the two directions.
                store = open_db(":memory:")
                try:
                    reject.add(failing)
                    first = cycle(store,sources,self.rules,"rules",channels,self.now)
                    self.assertEqual(first["delivery_errors"],1)
                    reject.clear()
                    cycle(store,{},self.rules,"rules",channels,self.now+10)
                    self.assertCountEqual([c for c,_ in accepted],["telegram","whatsapp"])
                    self.assertEqual(dict(store.execute("SELECT channel,attempts FROM deliveries"))[failing],2)
                    self.assertEqual(store.execute("SELECT count(*) FROM deliveries WHERE receipt IS NULL").fetchone()[0],0)
                finally:
                    store.close()

    def test_hourly_and_daily_digests_use_both_adapters(self):
        with fixture_services() as (sources,channels,accepted,_):
            cycle(self.db,sources,self.rules,"rules",channels,self.now)
            cycle(self.db,{},self.rules,"rules",channels,self.now+3600)
            self.assertEqual([ch for ch,txt in accepted if "Hourly digest" in txt],["telegram","whatsapp"])
            self.assertFalse(any("Daily digest" in txt for _,txt in accepted))
            cycle(self.db,{},self.rules,"rules",channels,self.now+3*3600)
            self.assertEqual([ch for ch,txt in accepted if "Daily digest" in txt],["telegram","whatsapp"])
            self.assertFalse(any("table tennis" in txt for _,txt in accepted))

    def test_analysis_failure_retries_after_restart_without_new_feed(self):
        with fixture_services() as (sources,channels,accepted,_):
            with patch("pipeline.worker.classify",side_effect=ValueError("Model unavailable")):
                out = cycle(self.db,sources,self.rules,"rules",channels,self.now)
            self.assertEqual(out["analysis_errors"],5)
            self.db.close()
            self.db = open_db(self.path)
            out = cycle(self.db,{},self.rules,"rules",channels,self.now+10)
            self.assertEqual(out["analysis_errors"],0)
            self.assertEqual(len(accepted),2)

    def test_topic_alone_is_not_an_urgent_correction(self):
        a = Article("https://press.example/meeting","Desk","neutral",title="Waterfront meeting agenda")
        self.assertEqual(classify(a,self.rules,"rules").urgency,"HIGH")

    def test_model_confidence_gate(self):
        a = Article("https://press.example/update","Desk","newsroom",title="Venue correction")
        payload = dict(urgency="CRITICAL",confidence=0.5,category="correction",event_slug="meeting",
                       headline="Venue correction",summary="The venue changed.")
        with patch.dict(os.environ,GEMINI_MODEL="test",GEMINI_API_KEY="local"), patch("pipeline.analysis.requests.post") as post:
            post.return_value.json.return_value={"candidates":[{"content":{"parts":[{"text":json.dumps(payload)}]}}]}
            self.assertEqual(classify(a,self.rules,"gemini").urgency,"MEDIUM")
            self.assertIn("Venue correction",post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])

if __name__=="__main__":
    unittest.main()
