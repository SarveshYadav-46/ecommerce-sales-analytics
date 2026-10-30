"""
Live Pipeline Dashboard Server
===============================
Standard-library HTTP server that:
1. Serves static dashboard files from project root
2. Exposes live API endpoints for pipeline status, triggering runs, and streaming logs
"""

import os
import sys
import json
import time
import threading
import subprocess
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from python.config import PATHS, get_db_url

# Shared pipeline execution state
PIPELINE_STATE = {
    "is_running": False,
    "current_action": None,
    "last_run_time": None,
    "last_run_status": "Success",
    "recent_logs": []
}
LOG_LOCK = threading.Lock()

def append_log(line: str):
    with LOG_LOCK:
        ts = time.strftime("%H:%M:%S")
        PIPELINE_STATE["recent_logs"].append(f"[{ts}] {line}")
        if len(PIPELINE_STATE["recent_logs"]) > 200:
            PIPELINE_STATE["recent_logs"].pop(0)

def execute_pipeline_task(action: str):
    append_log(f"Initiating pipeline action: '{action}'")
    PIPELINE_STATE["is_running"] = True
    PIPELINE_STATE["current_action"] = action
    start_time = time.time()

    py_exe = sys.executable

    try:
        if action == "full":
            cmd = [py_exe, str(PROJECT_ROOT / "python" / "run_pipeline.py")]
        elif action == "test":
            cmd = [py_exe, "-m", "pytest", "-v", str(PROJECT_ROOT / "tests" / "test_pipeline.py")]
        elif action == "rfm":
            cmd = [py_exe, str(PROJECT_ROOT / "python" / "customer_rfm_analysis.py")]
        elif action == "validate":
            cmd = [py_exe, str(PROJECT_ROOT / "python" / "validate_metrics.py")]
        elif action == "diagnostic":
            cmd = [py_exe, str(PROJECT_ROOT / "python" / "agent_verification_test.py")]
        else:
            cmd = [py_exe, str(PROJECT_ROOT / "python" / "run_pipeline.py")]

        append_log(f"Executing: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        for line in process.stdout:
            clean_line = line.strip()
            if clean_line:
                append_log(clean_line)

        process.wait()
        elapsed = round(time.time() - start_time, 2)
        if process.returncode == 0:
            PIPELINE_STATE["last_run_status"] = "Success"
            append_log(f"Action '{action}' COMPLETED SUCCESSFULLY in {elapsed}s ✓")
        else:
            PIPELINE_STATE["last_run_status"] = f"Failed (exit code {process.returncode})"
            append_log(f"Action '{action}' FAILED with exit code {process.returncode}")

    except Exception as e:
        PIPELINE_STATE["last_run_status"] = f"Error: {str(e)}"
        append_log(f"Execution exception: {e}")
    finally:
        PIPELINE_STATE["is_running"] = False
        PIPELINE_STATE["current_action"] = None
        PIPELINE_STATE["last_run_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

def get_live_warehouse_status():
    status = {
        "database_connected": False,
        "tables": {},
        "files": {},
        "pipeline_state": PIPELINE_STATE
    }

    # Check files
    for key, path in [
        ("raw_excel", PATHS["raw_excel"]),
        ("cleaned_sales", PATHS["cleaned_sales_csv"]),
        ("returns", PATHS["returns_csv"]),
        ("rfm", PATHS["rfm_csv"]),
        ("quality_report", PATHS["quality_report_json"]),
        ("validation_report", PATHS["data_dir"] / "metrics_validation_report.json"),
    ]:
        exists = path.exists()
        size_mb = round(path.stat().st_size / 1024 / 1024, 2) if exists else 0
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)) if exists else None
        status["files"][key] = {
            "exists": exists,
            "size_mb": size_mb,
            "last_modified": mtime
        }

    # Check MySQL DB
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(get_db_url())
        with engine.connect() as conn:
            status["database_connected"] = True
            for tbl in ["fact_sales", "fact_returns", "dim_customers", "dim_products", "dim_date", "customer_rfm"]:
                try:
                    cnt = conn.execute(text(f"SELECT COUNT(*) FROM {tbl};")).scalar()
                    status["tables"][tbl] = cnt
                except Exception:
                    status["tables"][tbl] = None
    except Exception as e:
        status["database_error"] = str(e)

    return status

class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(302)
            self.send_header("Location", "/tableau/live_dashboard.html")
            self.end_headers()
            return

        if parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = get_live_warehouse_status()
            self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))
            return

        if parsed.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with LOG_LOCK:
                logs_copy = list(PIPELINE_STATE["recent_logs"])
            self.wfile.write(json.dumps({
                "is_running": PIPELINE_STATE["is_running"],
                "current_action": PIPELINE_STATE["current_action"],
                "last_run_time": PIPELINE_STATE["last_run_time"],
                "last_run_status": PIPELINE_STATE["last_run_status"],
                "logs": logs_copy[-80:]
            }).encode("utf-8"))
            return

        # Serve static file
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/run":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}

            action = payload.get("action", "full")

            if PIPELINE_STATE["is_running"]:
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "A pipeline task is already executing.",
                    "current_action": PIPELINE_STATE["current_action"]
                }).encode("utf-8"))
                return

            # Launch background worker thread
            t = threading.Thread(target=execute_pipeline_task, args=(action,), daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "message": f"Pipeline action '{action}' triggered.",
                "action": action
            }).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

def run_server(port=8000):
    server = HTTPServer(("0.0.0.0", port), DashboardRequestHandler)
    print(f"================================================================")
    print(f" LIVE PIPELINE DASHBOARD SERVER RUNNING ON PORT {port}")
    print(f" Direct URL: http://localhost:{port}/tableau/live_dashboard.html")
    print(f" API Status: http://localhost:{port}/api/status")
    print(f"================================================================")
    append_log("Dashboard server started on port 8000.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer terminated by user.")
    finally:
        server.server_close()

if __name__ == "__main__":
    run_server(8000)
