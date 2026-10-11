"""The credential typed into a URL, taken out of it and carried beside it.

`https://user:password@host/` is how a staging site behind Basic authentication is
audited, and the URL is then a secret as well as an address (`openspec/specs/inputs/`
INP-7). Where it comes in, the userinfo is split off and set in `URL_CREDENTIALS_VAR`,
which every process the program starts inherits, and `safe_http.url_credentials` gives
it to that URL's own site and to nobody else. The runner does it in `main`; a script
started by hand, through `credentials_beside_argv` under its `__main__` guard.

It is not in `safe_http` because nothing here opens a connection, and
`tests/test_registry.py` counts a script that imports `safe_http` as one whose
connections reach the guard.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlparse

URL_CREDENTIALS_VAR = "SEO_URL_CREDENTIALS"


def split_userinfo(url: str) -> tuple[str, str]:
    """Remove only the authority's userinfo, preserving the rest as typed."""
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return url, ""
    if "@" not in netloc:
        return url, ""
    userinfo = netloc.rsplit("@", 1)[0]
    # Map parser-stripped controls back to positions in the original string.
    positions = [i for i, char in enumerate(url) if char not in "\t\r\n"]
    parsed_text = "".join(url[i] for i in positions)
    authority = parsed_text.index("//") + 2
    start = positions[authority]
    end = positions[authority + len(userinfo)] + 1
    return url[:start] + url[end:], userinfo


def credential_beside(url: str) -> tuple[str, str]:
    """`split_userinfo`, and the userinfo named in `URL_CREDENTIALS_VAR` for this
    process and its children, where `url_credentials` gives it to the URL's own site.

    The runner calls it where the URL comes in; a script started by hand, through
    `credentials_beside_argv`, for what was typed.
    """
    clean, userinfo = split_userinfo(url)
    if userinfo:
        os.environ[URL_CREDENTIALS_VAR] = _credential(clean, userinfo)
    return clean, userinfo


def _credential(clean: str, userinfo: str) -> str:
    parsed = urlparse(clean)
    return f"{parsed.scheme.lower()}://{userinfo}@{parsed.netloc}"


_TYPED_URL = re.compile(r"https?://", re.IGNORECASE)


def credentials_beside_argv(argv: list[str] | None = None) -> None:
    """Do for a script started by hand what the runner does at its own entrance.

    Started by the runner, a script is handed a URL with no credential in it and the
    credential beside it, in the environment. Started by hand it was handed what was
    typed, and measured on 11 October 2026 (`local/urlhand/`) four scripts gave that
    whole to somebody else's server: `pagespeed.py` to Google's PageSpeed API,
    `domain_safety_check.py` to Safe Browsing, `html_validator.py` to the W3C
    validator, `indexnow_checker.py --ping` to Bing — and every URL typed into a text
    slot, an `--entity` or a `--keyword`, went out as the text it was. A token alone
    never reached the site at all: Requests reads no credential out of `tok@host`.

    So every argument that holds an http(s) URL with userinfo, alone or after an
    `=` or a short option's letter, is split where it stands, and the userinfo goes
    beside it as the runner would put it. From there the script is in the state the
    runner leaves it in. Called under a `__main__` guard and never on import, like
    `utf8_streams`, and before the parser reads `sys.argv`. An argument without one
    changes nothing, the environment included: under the runner that is every one.

    Two URLs with different credentials cannot both travel in one variable, and
    asking either site without its own would be an audit of a 401, so that is
    refused before anything is asked. The same holds for a URL whose credential is
    not the one the process already carries: `seo_common.read_urls` sends a file of
    URLs through here after the command line has been, and a file naming another
    credential than the command line is refused as two on the command line are.
    """
    argv = sys.argv if argv is None else argv
    named = {}
    for index in range(1, len(argv)):
        found = _TYPED_URL.search(argv[index])
        if not found:
            continue
        before, typed = argv[index][:found.start()], argv[index][found.start():]
        clean, userinfo = split_userinfo(typed)
        if userinfo:
            argv[index] = before + clean
            named[_credential(clean, userinfo)] = clean
    carried = os.environ.get(URL_CREDENTIALS_VAR)
    if named and carried and carried not in named:
        named[carried] = split_userinfo(carried)[0]
    if len(named) > 1:
        raise SystemExit("the URLs given carry different credentials, and a process "
                         f"carries one ({URL_CREDENTIALS_VAR}): "
                         + ", ".join(sorted(named.values())))
    if named:
        os.environ[URL_CREDENTIALS_VAR] = next(iter(named))
