"""Everything a program asks for, written down and answered on this machine.

`tests/test_url_credentials.py` puts this directory first on a child's `PYTHONPATH` to
see what a program started by hand sends, and to whom, when the URL it was given
carries a credential. The question is about requests to outside services, so the
child cannot run under `SEO_LOOPBACK_ONLY`: that switch makes `safe_http` refuse every
other host before a request is built, and a request never attempted is not a request
made clean. Nothing leaves the machine all the same, because this module answers
every layer a request can leave by:

* a Requests adapter's `send`, which every `requests` call and every `safe_http`
  request reaches with its URL, headers and body still readable, TLS or not;
* a socket's `connect`, which is refused once it is written down: `tls_certificate.py`
  and anything else that opens its own socket;
* the resolver, which answers every name with one public address nothing connects
  to, and writes the name down, because the query is itself sent to somebody;
* an audit hook as the fence: a real connection to an address that is not loopback,
  or a real resolution of a name, ends the process with `EXIT_CODE`.

What is written is one JSON line per request, as the request would have gone out: the
target line, the headers and the body. `SEO_CAPTURE_LOG` names a directory, and every
process that loads this module writes to a file of its own there, created when it
starts and closed with an `end` line when it ends. Processes sharing one file were
measured on Windows on 11 October 2026 losing a quarter of their lines and tearing
some, because an append there is not atomic; a file only one process ever opens has
no other writer, and its threads take turns. A file without its `end` line belongs to
a process that is still writing or was killed in the middle, and `read` says so
rather than read it as whole.

The site is `SEO_CAPTURE_SITE`, an origin. It answers from the directory
`SEO_CAPTURE_ROOT` when the request carries `SEO_CAPTURE_AUTH` as its `Authorization`
and with a 401 when it does not, so a program that stops presenting the credential
sees the site refuse it, as a real one would. The same host over plain http redirects
to the site. Every other origin answers 200 with an empty JSON object.
`SEO_CAPTURE_CWD`, when set, is the directory the program runs in, so that what it
writes beside itself lands there and not in the tree the test was started from.
"""
import atexit
import io
import ipaddress
import json
import mimetypes
import os
import socket
import sys
import threading
from urllib.parse import urlsplit

EXIT_CODE = 97
# Every name resolves to this. It has to be public, or the guard in `safe_http` refuses
# it as private before a request is built — and the documentation ranges are reserved,
# which the guard refuses too. Nothing connects to it: `send` and `connect` answer first.
STAND_IN_ADDRESS = "8.8.8.8"
_lock = threading.Lock()
LOG = os.environ.get("SEO_CAPTURE_LOG", "")
SITE = os.environ.get("SEO_CAPTURE_SITE", "")
AUTH = os.environ.get("SEO_CAPTURE_AUTH", "")
ROOT = os.environ.get("SEO_CAPTURE_ROOT", "")
# The fixture tree names its own origin and its neighbour by these.
PLACEHOLDER = "http://127.0.0.1:8000"
PLACEHOLDER_EXTERNAL = "http://127.0.0.1:8001"
ELSEWHERE = "https://elsewhere.example"


_file = None
_owner = None


def record(kind: str, **fields) -> None:
    global _file, _owner
    line = json.dumps(dict(kind=kind, program=os.path.basename(sys.argv[0] or ""),
                           **fields), ensure_ascii=False)
    with _lock:
        if _owner != os.getpid():           # first line, or a child made by fork
            _owner = os.getpid()
            _file = open(os.path.join(LOG, f"{_owner}-{os.urandom(8).hex()}.jsonl"), "x",
                         encoding="utf-8")
        _file.write(line + "\n")
        _file.flush()


def _end() -> None:
    if _owner == os.getpid():
        # Whether the process ended carrying a credential the operator typed: a
        # program that read what was typed as a URL with userinfo in it carries one
        # (`lib/typed_credential.py`), and one that read it as a file name or as text
        # does not. The tests start every program with it cleared.
        record("end", credential=bool(os.environ.get("SEO_URL_CREDENTIALS")))


def read(directory: str) -> tuple[list[dict], list[str]]:
    """Every line every process wrote, and the files that are not whole: unreadable,
    or without the `end` line their process writes last."""
    lines, unfinished = [], []
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            text = f.read()
        try:
            written = [json.loads(line) for line in text.splitlines()]
        except ValueError:
            written = []
        if not written or written[-1]["kind"] != "end":
            unfinished.append(name)
        lines += [line for line in written if line["kind"] not in ("start", "end")]
    return lines, unfinished


def carried(directory: str) -> bool:
    """Whether a process of the start ended carrying a credential (see `_end`)."""
    for name in os.listdir(directory):
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            text = f.read()
        for line in text.splitlines():
            try:
                written = json.loads(line)
            except ValueError:
                continue
            if written["kind"] == "end" and written.get("credential"):
                return True
    return False


def _is_name(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str) or not host or host.lower() in ("localhost", "localhost."):
        return False
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return True
    return False


def _is_loopback_address(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True                     # a Unix socket
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str) or host.lower() in ("", "localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _served(path: str) -> tuple[int, dict, bytes]:
    relative = path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    target = os.path.normpath(os.path.join(ROOT, relative))
    if not target.startswith(os.path.normpath(ROOT)):
        return 404, {"Content-Type": "text/plain"}, b"not found"
    if os.path.isdir(target):
        target = os.path.join(target, "index.html")
    if not os.path.isfile(target):
        return 404, {"Content-Type": "text/html"}, b"<html><body>not found</body></html>"
    with open(target, "rb") as f:
        body = f.read()
    kind = mimetypes.guess_type(target)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind.endswith(("xml", "json")):
        body = (body.replace(PLACEHOLDER_EXTERNAL.encode(), ELSEWHERE.encode())
                .replace(PLACEHOLDER.encode(), SITE.encode()))
        kind += "; charset=utf-8"
    return 200, {"Content-Type": kind}, body


def answer(scheme: str, netloc: str, target: str, headers: dict) -> tuple[int, dict, bytes]:
    """What the stand-in for `scheme://netloc` answers to `target`."""
    site = urlsplit(SITE)
    if netloc.lower() == site.netloc.lower():
        if scheme == site.scheme:
            if headers.get("authorization") != AUTH:
                return 401, {"WWW-Authenticate": 'Basic realm="staging"',
                             "Content-Type": "text/plain"}, b"credential required"
            return _served(target)
        return 301, {"Location": f"{SITE}{target}", "Content-Length": "0"}, b""
    return 200, {"Content-Type": "application/json"}, b"{}"


def _install_requests() -> None:
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.response import HTTPResponse
    except ImportError:
        return

    def send(self, request, stream=False, timeout=None, verify=True, cert=None,
             proxies=None):
        parts = urlsplit(request.url)
        netloc = parts.netloc.rsplit("@", 1)[-1]
        target = self.request_url(request, None)
        headers = {k.lower(): v for k, v in request.headers.items()}
        body = request.body
        if hasattr(body, "read"):
            body = body.read()
        if isinstance(body, str):
            body = body.encode("utf-8")
        record("http", method=request.method, scheme=parts.scheme, origin=netloc,
               target=target, headers=headers,
               body=(body or b"").decode("utf-8", "replace"))
        status, answer_headers, payload = answer(parts.scheme, netloc, target, headers)
        answer_headers.setdefault("Content-Length", str(len(payload)))
        raw = HTTPResponse(body=io.BytesIO(payload), headers=answer_headers,
                           status=status, preload_content=False, decode_content=False,
                           request_url=request.url)
        return self.build_response(request, raw)

    HTTPAdapter.send = send


def _install_sockets() -> None:
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if _is_name(host):
            name = host.decode("ascii", "replace") if isinstance(host, bytes) else host
            record("resolve", origin=name)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     (STAND_IN_ADDRESS, port if isinstance(port, int) else 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    def gethostbyname(host):
        if _is_name(host):
            record("resolve", origin=host)
            return STAND_IN_ADDRESS
        return real_gethostbyname(host)

    real_gethostbyname = socket.gethostbyname
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    real_connect = socket.socket.connect

    def connect(self, address):
        if not _is_loopback_address(address):
            record("connect", origin=f"{address[0]}:{address[1]}")
            raise ConnectionRefusedError(f"stand-in: {address[0]} is not reached")
        return real_connect(self, address)

    socket.socket.connect = connect


def _fence(event, args) -> None:
    said = ""
    if event == "socket.connect" and not _is_loopback_address(args[1]):
        said = f"connected to {args[1]!r}"
    elif event in ("socket.getaddrinfo", "socket.gethostbyname") and _is_name(args[0]):
        said = f"resolved {args[0]!r}"
    if said:
        try:
            record("escaped", origin=said)
            _end()
        finally:
            sys.stderr.write(f"hand_capture: {said}\n")
            sys.stderr.flush()
            os._exit(EXIT_CODE)


if LOG:
    record("start")
    atexit.register(_end)
    sys.addaudithook(_fence)
    _install_sockets()
    _install_requests()
    if os.environ.get("SEO_CAPTURE_CWD"):
        os.chdir(os.environ["SEO_CAPTURE_CWD"])
