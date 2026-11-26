import argparse
import fcntl
import json
import os
import time
from pathlib import Path
from pipeline.demo import run_demo
from pipeline.delivery import destinations
from pipeline.worker import cycle, open_db

def main():
    parser = argparse.ArgumentParser(description="Monitor news and route relevant coverage.")
    parser.add_argument("mode", nargs="?", default="demo", choices=["demo","once","watch","status"])
    args = parser.parse_args()
    if args.mode == "demo":
        print(run_demo())
        print("\n[Local HTTP delivery confirmed by both Telegram and WhatsApp fixtures]")
        return 0
    state = Path(os.getenv("STATE_PATH","/data/monitor.sqlite3"))
    state.parent.mkdir(parents=True, exist_ok=True)
    db = open_db(state)
    try:
        if args.mode == "status":
            for row in db.execute("""SELECT m.tier,d.channel,d.attempts,CASE WHEN d.receipt IS NULL THEN 'pending'
                                     ELSE 'confirmed' END FROM deliveries d JOIN messages m ON m.id=d.message ORDER BY m.id"""):
                print(*row,sep=" | ")
            return 0
        with open(str(state)+".lock", "a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            destinations_ = destinations(os.environ)
            mode = os.getenv("CLASSIFIER","rules")
            if mode not in {"rules","gemini"} or (mode=="gemini" and not all(os.getenv(k) for k in ("GEMINI_MODEL","GEMINI_API_KEY"))):
                raise ValueError("Configure CLASSIFIER, and a model and key for Gemini mode")
            while True:
                sources = json.loads(Path(os.environ["SOURCES_PATH"]).read_text())
                watchlist = json.loads(Path(os.environ["WATCHLIST_PATH"]).read_text())
                result = cycle(db,sources,watchlist,mode,destinations_)
                print(json.dumps(result),flush=True)
                if args.mode=="once":
                    return int(bool(result["analysis_errors"] or result["delivery_errors"]))
                time.sleep(max(1,int(os.getenv("POLL_SECONDS","300"))))
    finally:
        db.close()

if __name__ == "__main__":
    raise SystemExit(main())
