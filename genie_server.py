#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import threading
import traceback
import uuid
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
PIPELINE_DIR = ROOT / "genie_pipeline"
DATA_DIR = Path(os.environ.get("GENIE_DATA_DIR", str(ROOT / "genie_web_jobs"))).resolve()
JOBS_DIR = DATA_DIR
UPLOADS_DIR = JOBS_DIR / "uploads"
SAMPLE_REPORT_PATH = ROOT / "sample-report.json"
DEFAULT_TRAITS = ["height", "hair-color", "left-handedness"]
ACCESS_REQUESTS_PATH = JOBS_DIR / "access_requests.jsonl"
PORTAL_COOKIE = "genie_portal"
PORTAL_COOKIE_VALUE = "granted"
PORTAL_ACCESS_CODE = os.environ.get("GENIE_PORTAL_CODE", "genie-private-beta")
COOKIE_SECURE = os.environ.get("GENIE_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
PIPELINE_ENABLED = os.environ.get("GENIE_ENABLE_PIPELINE", "1").strip().lower() not in {"0", "false", "no", "off"}
HOST = os.environ.get("GENIE_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", os.environ.get("GENIE_PORT", "8000")))
ROOT_STATIC_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".css", ".js", ".svg"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip().lower())
    return cleaned.strip("-") or "sample"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def portal_cookie_header(value: str, *, max_age: int | None = None) -> str:
    parts = [f"{PORTAL_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    if COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


def parse_multipart(handler: BaseHTTPRequestHandler) -> dict[str, list[dict]]:
    content_type = handler.headers.get("Content-Type", "")
    content_length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(content_length)
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("utf-8") + body
    )
    fields: dict[str, list[dict]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        fields.setdefault(name, []).append({
            "filename": part.get_filename(),
            "value": part.get_payload(decode=True),
        })
    return fields


def prepare_vcf(input_path: Path, work_dir: Path) -> Path:
    prepared_path = work_dir / "input.vcf.gz"
    if input_path.suffixes[-2:] == [".vcf", ".gz"]:
        shutil.copy2(input_path, prepared_path)
    elif input_path.suffix == ".vcf":
        subprocess.run(
            ["bcftools", "view", "-Oz", "-o", str(prepared_path), str(input_path)],
            check=True,
        )
    else:
        raise RuntimeError("Upload must be a .vcf or .vcf.gz file.")

    subprocess.run(["tabix", "-f", "-p", "vcf", str(prepared_path)], check=True)
    return prepared_path


def run_pipeline_job(job_dir: Path, uploaded_path: Path, sample_name: str, genome_build: str, traits: list[str]) -> None:
    status_path = job_dir / "status.json"
    run_dir = job_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_dir / "job.log"

    def update(**kwargs: object) -> None:
        current = read_json(status_path)
        current.update(kwargs)
        write_json(status_path, current)

    try:
        with log_path.open("a", encoding="utf-8") as log_handle:
            update(status="preparing", message="Preparing uploaded VCF for indexed queries.", updated_at=now_iso())
            prepared_vcf = prepare_vcf(uploaded_path, run_dir)

            update(status="scoring", message="Running bcftools and plink2 scoring pipeline.", updated_at=now_iso())
            subprocess.run(
                [
                    "python3",
                    str(PIPELINE_DIR / "run_vcf_pipeline.py"),
                    "--vcf",
                    str(prepared_vcf),
                    "--manifest",
                    str(PIPELINE_DIR / "pgs_candidates.json"),
                    "--outdir",
                    str(run_dir / "pipeline"),
                    "--genome-build",
                    genome_build,
                    "--only-traits",
                    ",".join(traits),
                ],
                cwd=str(ROOT),
                check=True,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )

            update(status="deriving", message="Deriving simple single-variant traits.", updated_at=now_iso())
            simple_traits_path = run_dir / "simple_traits.json"
            subprocess.run(
                [
                    "python3",
                    str(PIPELINE_DIR / "derive_simple_traits.py"),
                    "--vcf",
                    str(prepared_vcf),
                    "--out",
                    str(simple_traits_path),
                ],
                cwd=str(ROOT),
                check=True,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )

            update(status="building_report", message="Assembling Genie-style report JSON.", updated_at=now_iso())
            report_path = run_dir / "report.json"
            subprocess.run(
                [
                    "python3",
                    str(PIPELINE_DIR / "build_pipeline_report.py"),
                    "--pipeline-summary",
                    str(run_dir / "pipeline" / "summary.json"),
                    "--manifest",
                    str(PIPELINE_DIR / "pgs_candidates.json"),
                    "--simple-traits",
                    str(simple_traits_path),
                    "--out",
                    str(report_path),
                ],
                cwd=str(ROOT),
                check=True,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )

        pipeline_summary = read_json(run_dir / "pipeline" / "summary.json")
        report = read_json(report_path)
        update(
            status="completed",
            message="Report ready.",
            updated_at=now_iso(),
            completed_at=now_iso(),
            report=report,
            report_path=str(report_path),
            pipeline_summary=pipeline_summary,
            sample_name=sample_name,
            log_path=str(log_path),
        )
    except Exception as exc:
        update(
            status="failed",
            message=str(exc),
            updated_at=now_iso(),
            error={
                "type": exc.__class__.__name__,
                "detail": str(exc),
                "traceback": traceback.format_exc(),
            },
            log_path=str(log_path),
        )


class GenieHandler(BaseHTTPRequestHandler):
    server_version = "GeniePrototypeHTTP/0.1"

    def cookie_value(self, name: str) -> str | None:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            if key == name:
                return value
        return None

    def has_portal_access(self) -> bool:
        return self.cookie_value(PORTAL_COOKIE) == PORTAL_COOKIE_VALUE

    def parse_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/healthz":
            self.respond_json({"ok": True, "pipeline_enabled": PIPELINE_ENABLED, "data_dir": str(DATA_DIR)})
            return
        if path == "/":
            self.serve_file(ROOT / "genie-landing.html", "text/html; charset=utf-8")
            return
        if path == "/portal":
            self.serve_file(ROOT / "genie-portal.html", "text/html; charset=utf-8")
            return
        if Path(path).suffix.lower() in ROOT_STATIC_EXTENSIONS:
            self.serve_file(ROOT / path.lstrip("/"), self.guess_content_type(path))
            return
        if path == "/api/sample-report":
            self.respond_json(read_json(SAMPLE_REPORT_PATH))
            return
        if path == "/api/session":
            self.respond_json({"authorized": self.has_portal_access()})
            return
        if path == "/api/config":
            self.respond_json({"pipeline_enabled": PIPELINE_ENABLED})
            return
        if path.startswith("/api/jobs/"):
            if not self.has_portal_access():
                self.respond_json({"error": "Portal access required."}, status=HTTPStatus.FORBIDDEN)
                return
            job_id = path.split("/")[-1]
            status_path = JOBS_DIR / job_id / "status.json"
            if not status_path.exists():
                self.respond_json({"error": "Job not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self.respond_json(read_json(status_path))
            return
        if path.startswith("/api/reports/"):
            if not self.has_portal_access():
                self.respond_json({"error": "Portal access required."}, status=HTTPStatus.FORBIDDEN)
                return
            job_id = path.split("/")[-1]
            report_path = JOBS_DIR / job_id / "run" / "report.json"
            if not report_path.exists():
                self.respond_json({"error": "Report not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self.respond_json(read_json(report_path))
            return
        if path.startswith("/genie_pipeline/") or path.startswith("/genie_web_jobs/"):
            self.serve_file(ROOT / path.lstrip("/"), self.guess_content_type(path))
            return
        self.respond_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/access-request":
            payload = self.parse_json_body()
            record = {
                "created_at": now_iso(),
                "name": (payload.get("name") or "").strip(),
                "email": (payload.get("email") or "").strip(),
                "clinic": (payload.get("clinic") or "").strip(),
                "notes": (payload.get("notes") or "").strip(),
            }
            if not record["name"] or not record["email"]:
                self.respond_json({"error": "Name and email are required."}, status=HTTPStatus.BAD_REQUEST)
                return
            append_jsonl(ACCESS_REQUESTS_PATH, record)
            self.respond_json({"ok": True, "message": "Access request saved."}, status=HTTPStatus.ACCEPTED)
            return

        if parsed.path == "/api/portal-login":
            payload = self.parse_json_body()
            if (payload.get("access_code") or "").strip() != PORTAL_ACCESS_CODE:
                self.respond_json({"error": "Invalid access code."}, status=HTTPStatus.FORBIDDEN)
                return
            self.respond_json(
                {"ok": True, "authorized": True},
                headers={"Set-Cookie": portal_cookie_header(PORTAL_COOKIE_VALUE)},
            )
            return

        if parsed.path == "/api/portal-logout":
            self.respond_json(
                {"ok": True},
                headers={"Set-Cookie": portal_cookie_header("", max_age=0)},
            )
            return

        if parsed.path != "/api/jobs":
            self.respond_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return
        if not self.has_portal_access():
            self.respond_json({"error": "Portal access required."}, status=HTTPStatus.FORBIDDEN)
            return
        if not PIPELINE_ENABLED:
            self.respond_json(
                {"error": "Uploads are not enabled on this deployment yet."},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return

        fields = parse_multipart(self)
        upload = fields.get("vcf_file", [None])[0]
        if upload is None or not upload.get("filename"):
            self.respond_json({"error": "Missing uploaded VCF file."}, status=HTTPStatus.BAD_REQUEST)
            return

        filename = Path(upload["filename"]).name
        if not (filename.endswith(".vcf") or filename.endswith(".vcf.gz")):
            self.respond_json({"error": "Upload must be a .vcf or .vcf.gz file."}, status=HTTPStatus.BAD_REQUEST)
            return

        def field_text(name: str, default: str = "") -> str:
            item = fields.get(name, [None])[0]
            if item is None:
                return default
            return item["value"].decode("utf-8").strip()

        sample_name = field_text("sample_name") or Path(filename).stem.replace(".vcf", "")
        genome_build = field_text("genome_build", "GRCh37")
        traits = [item for item in field_text("traits", ",".join(DEFAULT_TRAITS)).split(",") if item]
        job_id = uuid.uuid4().hex[:12]
        job_dir = JOBS_DIR / job_id
        upload_dir = job_dir / "upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploaded_path = upload_dir / filename

        with uploaded_path.open("wb") as handle:
            handle.write(upload["value"])

        status_payload = {
            "job_id": job_id,
            "status": "queued",
            "message": "Upload received.",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "sample_name": safe_slug(sample_name),
            "genome_build": genome_build,
            "traits": traits,
            "uploaded_filename": filename,
        }
        write_json(job_dir / "status.json", status_payload)

        worker = threading.Thread(
            target=run_pipeline_job,
            args=(job_dir, uploaded_path, safe_slug(sample_name), genome_build, traits),
            daemon=True,
        )
        worker.start()

        self.respond_json(status_payload, status=HTTPStatus.ACCEPTED)

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.respond_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def guess_content_type(self, path: str) -> str:
        if path.endswith(".json"):
            return "application/json; charset=utf-8"
        if path.endswith(".jpg") or path.endswith(".jpeg"):
            return "image/jpeg"
        if path.endswith(".mp4"):
            return "video/mp4"
        if path.endswith(".png"):
            return "image/png"
        if path.endswith(".gif"):
            return "image/gif"
        if path.endswith(".webp"):
            return "image/webp"
        if path.endswith(".svg"):
            return "image/svg+xml"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        if path.endswith(".js"):
            return "text/javascript; charset=utf-8"
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        return "application/octet-stream"

    def respond_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), GenieHandler)
    print(f"Serving Genie prototype on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
