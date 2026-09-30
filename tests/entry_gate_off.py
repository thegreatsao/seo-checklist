"""`checklist_runner` with its entry gate removed — an instrument, never a runner.

`tests/test_entry_answers.py` runs this beside the real runner. `fetch_page` is replaced
by one that hands the run whatever the entry URL answered — any status, any content
type — as a readable page, and `is_private_host` answers False so the outside-world gate
does not hide what the entry gate hides (TE-167 is `api`). Nothing else changes, so a
verdict that differs from the shipped runner's on the same origin is one the entry gate
decided. When nothing answers, the run goes on with no page, as a run whose entry
answered and was not HTML would.

Written at 0.130.0. The measurement it came from is `local/entry-gate/` (outside git).
"""
import os
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "skills", "seo-checklist", "scripts")
sys.path.insert(0, SCRIPTS)

import checklist_runner as runner  # noqa: E402
import lib.safe_http as safe_http  # noqa: E402


def fetch_page(url, enforce_guard=True):
    try:
        resp = safe_http.safe_get(url, timeout=15)
    except Exception:  # noqa: BLE001 - nothing answered; the run goes on without a page
        # No page at all rather than an empty one: an empty document would be graded
        # by the offline checks as a page with no headings, which is this instrument
        # inventing failures rather than removing a gate.
        return runner.Fetch(path="", error="", final_url=url, guard="", status=None)
    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w",
                                      encoding="utf-8")
    tmp.write(resp.text or "")
    tmp.close()
    return runner.Fetch(path=tmp.name, error="",
                        final_url=getattr(resp, "url", "") or url, guard="",
                        status=resp.status_code)


runner.fetch_page = fetch_page
safe_http.is_private_host = lambda url: False
sys.argv[0] = os.path.join(SCRIPTS, "checklist_runner.py")
sys.exit(runner.main())
