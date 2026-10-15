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


_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_AUTHORITY_END = re.compile(r"[/?#]")


def schemeless(typed: str) -> tuple[str, bool] | None:
    """`typed` read as a URL typed without a scheme whose authority carries userinfo —
    `user:password@host`, `tok@host:8443/a` — with the scheme every program puts in
    front of such a URL, `https://`, and whether it could as well be an e-mail address:
    `name@host` with nothing after the host, which only the slot it was typed in can
    tell apart. None for anything else, a URL typed with its scheme included.

    Measured on 14 October 2026 at 0.163.0 (`local/schemeless/`), neither entrance split
    such a URL, and the scheme was put in front of it after both: `pagespeed.py` gave the
    credential to Google, the runner gave it to Safe Browsing and wrote it into its
    results, and the site was never given it.
    """
    if (not typed or _SCHEME.match(typed) or any(char.isspace() for char in typed)
            or typed.lower().startswith("mailto:")):
        return None
    authority = _AUTHORITY_END.split(typed, 1)[0]
    if not authority.rpartition("@")[0]:
        return None
    url = f"https://{typed}"
    try:
        parsed = urlparse(url)
        _ = parsed.port                 # a port that is not a number raises
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    return url, authority == typed and ":" not in typed


def credential_beside(url: str) -> tuple[str, str]:
    """`split_userinfo`, and the userinfo named in `URL_CREDENTIALS_VAR` for this
    process and its children, where `url_credentials` gives it to the URL's own site.

    The runner calls it where the URL comes in; a script started by hand, through
    `credentials_beside_argv`, for what was typed. The runner's URL is a URL whatever
    its shape, so one typed without a scheme is given the scheme here first.
    """
    read = schemeless(url)
    if read:
        url = read[0]
    clean, userinfo = split_userinfo(url)
    if userinfo:
        os.environ[URL_CREDENTIALS_VAR] = _credential(clean, userinfo)
    return clean, userinfo


def _credential(clean: str, userinfo: str) -> str:
    parsed = urlparse(clean)
    return f"{parsed.scheme.lower()}://{userinfo}@{parsed.netloc}"


_TYPED_URL = re.compile(r"https?://", re.IGNORECASE)
# Typed, and shaped like an e-mail address as much as like a URL: see `scheme_added`.
_maybe_text: set[str] = set()


def _option_value(argument: str) -> tuple[str, str]:
    """`argument` as the option it names and the value typed with it: `--site=VALUE`,
    `-sVALUE`, or a value alone."""
    if argument.startswith("--"):
        name, equals, value = argument.partition("=")
        return (name + equals, value) if equals else (argument, "")
    if argument.startswith("-"):
        return argument[:2], argument[2:]
    return "", argument


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
    beside it as the runner would put it. So is one typed without a scheme
    (`schemeless`), which gets `https://` in front of it as it would have later; but
    `name@host` with nothing after the host is an e-mail address as much as a URL,
    and is left as typed until the program reads it as a URL (`read_as_url`). From there the script is in the state the
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
        if found:
            before, typed = argv[index][:found.start()], argv[index][found.start():]
        else:
            before, typed = _option_value(argv[index])
            read = schemeless(typed)
            if not read:
                continue
            if read[1]:
                _maybe_text.add(typed)
                continue
            typed = read[0]
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


def read_as_url(typed: str, scheme: str = "https") -> str:
    """`typed`, which the program is about to read as a URL, as that URL.

    An address the entrance kept as typed because it could be an e-mail address is a
    URL from here on: `scheme://` goes in front of it, its userinfo is split off and
    goes beside it as a credential typed with its scheme does, and the one-credential
    rule holds for it. Anything else comes back as it is. Typed where text was asked
    for, an address never comes here and stays text.

    A program calls it once for each argument it reads as a URL, where it takes its
    arguments, and uses what it returns from there on (`seo_common.read_source` for
    one that reads a URL or a saved page). Measured on 15 October 2026 at 0.164.0
    (`local/printtok/`), programs that read it only where they fetched went on showing
    what was typed — eighteen of them printed `tok@host`, token and all — and some went
    on using it, `internal_links.py` naming no domain.
    """
    if typed not in _maybe_text:
        return typed
    argv = ["", f"{scheme}://{typed}"]
    credentials_beside_argv(argv)
    return argv[1]


def read_as_file(typed: str) -> str:
    """`typed`, which the program is about to open as a file, as that file name: never a
    URL from here on. `name@host` kept as typed because it could be an e-mail address
    stops being a candidate, so that wherever the program goes on to give the name a
    scheme — the page's address, the base its links are resolved against — it is given
    the scheme and nothing else, as a string nobody typed is.

    Measured on 15 October 2026 at 0.165.0 (`local/printtok/saved-before-758f419.txt`),
    eight programs handed a saved page named `tok@host` read the page and then, taking its
    name for the page's address, ended carrying `tok` as the credential of `host`.
    """
    _maybe_text.discard(typed)
    return typed


def scheme_added(url: str, scheme: str = "https") -> str:
    """`scheme://url`: how every place that gives a typed string its scheme gives it,
    `read_as_url` included. A string nobody typed is given its scheme and nothing
    else: a page's link is not the operator's credential."""
    return read_as_url(url, scheme) if url in _maybe_text else f"{scheme}://{url}"
