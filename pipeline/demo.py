"""Local HTTP source and provider fixtures. The worker uses its real outbound adapters."""
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from tempfile import TemporaryDirectory
from pipeline.delivery import destinations
from pipeline.worker import cycle, open_db

ROOT = Path(__file__).resolve().parents[1]
@contextmanager
def fixture_services():
    accepted, rejected = [], set()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def reply(self, code, data, mime="application/json"):
            raw = json.dumps(data).encode() if mime == "application/json" else data
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path in ("/bulletin.xml", "/newsdesk.xml"):
                return self.reply(200,(ROOT/"examples"/self.path[1:]).read_bytes(), "application/xml")
            self.reply(404, {})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/botlocal/sendMessage" and body.get("chat_id") == "demo-telegram" and body.get("text"):
                channel,text = "telegram",body["text"]
            elif self.path == "/waInstance001/sendMessage/local" and body.get("chatId") == "demo-whatsapp" and body.get("message"):
                channel,text = "whatsapp",body["message"]
            else:
                return self.reply(400, {"error":"Unexpected provider request"})
            if channel in rejected:
                return self.reply(503,{})
            accepted.append((channel,text))
            result = {"ok":True,"result":{"message_id":len(accepted)}} if channel=="telegram" else {"idMessage":str(len(accepted))}
            self.reply(200,result)
    with ThreadingHTTPServer(("127.0.0.1",0),Handler) as http:
        thread = Thread(target=http.serve_forever,daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{http.server_port}"
        channels = destinations({"TELEGRAM_BOT_TOKEN":"local","TELEGRAM_CHAT_ID":"demo-telegram",
                                 "GREEN_API_URL":url,"GREEN_API_INSTANCE_ID":"001","GREEN_API_TOKEN":"local",
                                 "WHATSAPP_GROUP_ID":"demo-whatsapp"}, telegram_base=url)
        sources = {"rss_sources":[{"name":name,"rss_url":url+"/"+file} for name,file in
                                  [("City Clerk","bulletin.xml"),("Harbour Desk","newsdesk.xml")]]}
        try:
            yield sources,channels,accepted,rejected
        finally:
            http.shutdown()
            thread.join()

def run_demo():
    watchlist = json.loads((ROOT/"examples/watchlist.json").read_text())
    with TemporaryDirectory() as temp, fixture_services() as (sources,channels,accepted,_):
        db = open_db(Path(temp)/"demo.db")
        try:
            outcome = cycle(db,sources,watchlist,"rules",channels)
            if outcome["analysis_errors"] or outcome["delivery_errors"] or len(accepted)!=2 or dict(accepted).get("telegram") != dict(accepted).get("whatsapp"):
                raise RuntimeError("The two local receivers did not confirm the same alert")
            return dict(accepted)["telegram"]
        finally:
            db.close()
