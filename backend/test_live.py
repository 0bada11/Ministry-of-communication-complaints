"""Concurrency checks against a real uvicorn server.

test_api.py drives the app in-process, which serialises every request and so
cannot catch threadpool problems. This starts an actual server and fires
overlapping requests at it — the shape of traffic the dashboard produces when
it refreshes the table and the statistics at the same time.

Run:  python test_live.py
"""

import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
BACKEND = Path(__file__).resolve().parent

passed = failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def get(path: str) -> int:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:
        return 0


def wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get("/api/health") == 200:
            return True
        time.sleep(0.4)
    return False


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="moct_live_"))
    env_patch = {"MOCT_DATA_DIR": str(data_dir)}

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=BACKEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**dict(__import__("os").environ), **env_patch},
    )

    try:
        if not wait_for_server():
            print("  FAIL  server did not start")
            return 1

        print("\n[single requests]")
        for path in ("/api/health", "/api/meta", "/api/stats?days=14",
                     "/api/complaints?per_page=7", "/api/complaints.csv", "/"):
            check(f"GET {path}", get(path) == 200)

        print("\n[concurrent requests]")
        # The dashboard fires these together after every status change.
        paths = [
            "/api/stats?days=14",
            "/api/complaints?per_page=7&page=1",
            "/api/complaints?status=new&per_page=7",
            "/api/meta",
        ] * 15

        with ThreadPoolExecutor(max_workers=12) as pool:
            codes = list(pool.map(get, paths))

        bad = [code for code in codes if code != 200]
        check(f"{len(codes)} overlapping requests all return 200",
              not bad, f"non-200 responses: {sorted(set(bad))}")

        print("\n[concurrent writes]")
        # Two clients advancing different complaints at the same moment.
        def submit(index: int) -> int:
            body = (
                '{"citizen_name":"مواطن %d","citizen_phone":"09%08d",'
                '"governorate":"دمشق","title":"شكوى اختبار رقم %d",'
                '"description":"وصف تجريبي لاختبار التزامن على قاعدة البيانات رقم %d."}'
            ) % (index, index, index, index)
            request = urllib.request.Request(
                f"{BASE}/api/complaints",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
            except Exception:
                return 0

        with ThreadPoolExecutor(max_workers=8) as pool:
            write_codes = list(pool.map(submit, range(16)))

        check("16 concurrent submissions all return 201",
              all(code == 201 for code in write_codes),
              f"codes: {sorted(set(write_codes))}")

        listing = urllib.request.urlopen(f"{BASE}/api/complaints?per_page=100", timeout=20)
        import json
        page = json.loads(listing.read())
        references = [item["reference_no"] for item in page["items"]]
        check("every reference number is unique",
              len(references) == len(set(references)),
              f"{len(references)} rows, {len(set(references))} unique")

    finally:
        server.terminate()
        try:
            output = server.communicate(timeout=10)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            server.kill()
            output = server.communicate()[0].decode("utf-8", "replace")
        shutil.rmtree(data_dir, ignore_errors=True)

    print()
    print("[server log]")
    check("server logged no tracebacks", "Traceback" not in output,
          output[-700:] if "Traceback" in output else "")

    print(f"\n{'=' * 46}\n  {passed} passed, {failed} failed\n{'=' * 46}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
