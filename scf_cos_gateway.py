"""SCF image runtime: credentials arrive on the first HTTP invocation."""
from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import threading

MAX_POOL_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 6 * 1024 * 1024


def fetch_accounts(headers, *, client_factory=None):
    from overstats.config.account_pool import decode_account_pool
    credentials = [headers.get(name, "") for name in (
        "X-Scf-Secret-Id", "X-Scf-Secret-Key", "X-Scf-Session-Token")]
    if not all(credentials):
        print("[scf] stage=credentials result=missing_runtime_role_headers", flush=True)
        raise ValueError("SCF runtime role credentials are missing")
    print("[scf] stage=credentials result=ok", flush=True)
    if client_factory is None:
        from qcloud_cos import CosConfig, CosS3Client
        client = CosS3Client(CosConfig(
            Region=os.environ["OVERSTATS_ACCOUNTS_COS_REGION"],
            SecretId=credentials[0], SecretKey=credentials[1], Token=credentials[2],
            Scheme="https", Timeout=20))
    else:
        client = client_factory(*credentials)
    print("[scf] stage=cos_download result=starting", flush=True)
    try:
        response = client.get_object(
            Bucket=os.environ["OVERSTATS_ACCOUNTS_COS_BUCKET"],
            Key=os.environ["OVERSTATS_ACCOUNTS_COS_KEY"])
    except Exception as exc:
        # Only allow known service codes. Exception text may contain credentials.
        code = "unclassified"
        try:
            candidate = exc.get_error_code()
            if candidate in {"AccessDenied", "NoSuchKey", "NoSuchBucket", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken", "RequestTimeTooSkewed"}:
                code = candidate
        except Exception:
            pass
        print(f"[scf] stage=cos_download result=failed code={code}", flush=True)
        raise
    stream = response["Body"].get_raw_stream()
    try:
        raw = stream.read(MAX_POOL_BYTES + 1)
    finally:
        stream.close()
    if len(raw) > MAX_POOL_BYTES:
        raise ValueError("Account object exceeds 2 MiB")
    print("[scf] stage=account_json result=validating", flush=True)
    try:
        accounts = decode_account_pool(raw)
    except ValueError:
        print("[scf] stage=account_json result=invalid_format_or_accounts", flush=True)
        raise
    print(f"[scf] stage=account_json result=ok count={len(accounts)}", flush=True)
    return accounts


class CoreRuntime:
    def __init__(self):
        self.lock = threading.Lock()
        self.server = None

    def ensure_started(self, headers):
        with self.lock:
            if self.server is None:
                accounts = fetch_accounts(headers)
                print("[scf] stage=core_start result=starting", flush=True)
                from overstats.config import loader
                loader.set_external_accounts(accounts)
                # One import/start per instance, only after credentials resolve.
                from overstats.src import create_server
                self.server = create_server(loader.get_api_config())
                threading.Thread(target=self.server.serve_forever, daemon=True).start()
                print(f"[scf] account pool loaded: count={len(accounts)}", flush=True)
            return self.server.server_address[1]


def handler_for(runtime):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass  # Do not log URLs, request bodies or credential headers.

        def error(self, status, message):
            body = ('{"ok":false,"error":"' + message + '"}').encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def forward(self):
            if self.headers.get("Transfer-Encoding"):
                self.error(400, "content_length_required")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.error(400, "invalid_content_length")
                return
            if not 0 <= length <= MAX_REQUEST_BYTES:
                self.error(413, "request_too_large")
                return
            body = self.rfile.read(length)
            try:
                port = runtime.ensure_started(self.headers)
            except Exception:
                # COS errors may contain signed URLs: never include exception text.
                print("[scf] account/core initialization failed; check COS settings, role permission and account JSON", flush=True)
                self.error(503, "scf_account_initialization_failed")
                return
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
            try:
                connection.request(self.command, self.path, body=body, headers={
                    "Content-Type": self.headers.get("Content-Type", "application/json"),
                    "Connection": "close",
                })
                response = connection.getresponse()
            except Exception:
                connection.close()
                self.error(502, "scf_core_connection_failed")
                return
            try:
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {"connection", "transfer-encoding", "server", "date", "keep-alive"}:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
            finally:
                connection.close()
                self.close_connection = True

        do_GET = forward
        do_POST = forward

    return Handler


def main():
    # cwd was prepared by scf_bootstrap; import only that private package copy.
    sys.path.insert(0, str(Path.cwd()))
    os.environ["OVERSTATS_API_HOST"] = "127.0.0.1"
    os.environ["OVERSTATS_API_PORT"] = "0"
    server = ThreadingHTTPServer(("0.0.0.0", 9000), handler_for(CoreRuntime()))
    print("[scf] listening on :9000; awaiting runtime-role credentials", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
