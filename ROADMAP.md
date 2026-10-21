# Roadmap to 1.0

`KNOWN-ISSUES.md` says what is wrong. This says where it stops.

A version number that does not mean anything is a number nobody can argue with, so
1.0 is defined here as a claim that can be checked:

> **Every item in the registry either carries a verdict or a stated structural reason
> it cannot; every number a verdict rests on is either measured or declared unmeasured;
> and the document says what the code does.**

That definition has not changed since 0.15.0 and does not need to. What follows is
where the tree stands against it, with the command that prints each number.

**Every count below is read by `tests/test_prose_counts.py`**, which derives it from the
tree and fails when this file disagrees. That is new at 0.111.0 and it is the reason
this section carries no version in its heading. Twice before, this file described a tree
that no longer existed: until 0.87.1 it planned releases that had shipped sixty-seven
releases earlier, and after 0.87.1 it said "where the tree stands, 0.87.1" for
twenty-two more. Nothing reads a roadmap on a schedule, so something has to read it on
every build.

---

## Where the tree stands

### The specification

Since 0.92.0 the tree has carried a written specification, 12 documents under
`openspec/specs/`, and each requirement in it names what holds it. That is the most
direct measure of the third clause there is, and the one this file did not have when
it was last written:

```
.venv/Scripts/python.exe skills/seo-checklist/tools/spec_debt.py
```

| | count | what it means |
|---|---|---|
| requirements | 158 | across 12 documents |
| enforced | 132 | held by something that fails when the requirement is violated |
| partial | 21 | held for part of what the requirement says |
| unread | 1 | held by nothing — `declarations` DEC-1 |
| bounded | 4 | the subject is outside the program; no test could observe a violation |

The `partial` column is where the work is, and a count does not say how much of each row
is held — read the document. The largest single debt is `registry` REG-6: five items
measured something other than their titles, all five were repaired by 0.108.0, and every
one was found by a person reading a rule against its title. Since 0.114.0
`tools/audit_item_readings.py` holds a written reading of every rule-carrying item
against its title and rule, and reddens when either changes until the pair is re-read;
since 0.122.0 no reading is owed. Whether a reading is *true* is still a person's
judgement, which is why REG-6 stays `partial`.

### Clause 1 — a verdict, or a stated reason there is none

`tests/census.json` records what every item answered across every tree this repository
can serve:

```
.venv/Scripts/python.exe tests/verdict_census.py --check tests/census.json
```

| | count | what it means |
|---|---|---|
| answered somewhere, never FAIL | 1 | a rule whose failure the entry gate hides |
| answered somewhere, never PASS | 2 | the mirror |
| never answered anywhere | 23 | each needs an outside service or key, and the census names which |

F06 (0.175.0) took both other rows to items, one at a time, with what each was expected
to be written down before anything was run (`docs/sprint-20261021-F06.md`). Of the 54,
27 lacked a page, an artifact or a key on every tree served here, and seven corpus trees and
their inputs now fail each of them for the reason its title names; one, `TE-167`, sat
behind the gate for hosts only this machine reaches although no outside service is in its
question, and now answers there. The 23 still silent each need an outside service or a key,
and the census prints which beside each one — read through the runner's own gate, so an
item that could answer offline fails `test_census.py` by name instead of being excused in a
sentence like the one this row used to carry.

`AR-153` and `MD-184` could not fail as registered, and what each should assert was
Anton's decision: MD-184 is answered by the entry page alone and fails one that references
no image; AR-153 reads the shared crawl and compares each topic's hub and spokes, on a topic
read crudely from title words. The one still never seen failing is `SE-118`, which fails
only on a certificate that also stops the audit's own request for the entry page, so the
entry gate turns the failure into NO_DATA — the defect 0.130.0 repaired for `CI-003` — and
the census marks it in its output (`CI-014` has the same gap for a redirect loop, and fails
here on a redirect with no `Location`).

The two that were never seen passing are `AR-158`, whose visible-breadcrumb half no
fixture carries, and `GEO-006`, whose script reads the JSON-LD graph with no boundary.
`GO-138` left this row at 0.123.0: the good fixture's sitemap had listed a page its
robots.txt forbids, and it no longer does.

### Clause 2 — every number measured or declared unmeasured

```
.venv/Scripts/python.exe skills/seo-checklist/tools/audit_thresholds.py
```

| basis | count |
|---|---|
| standard | 20 |
| measured | 14 |
| convention | 97 |
| inherited | 0 |
| no basis | 0 |
| **numbers a verdict depends on** | **131** |

**`inherited` at 0 of 131 closes what was the largest single gap between this tree and 1.0.** It was
75 of 144 at 0.87.1 and 77 of 164 until 0.167.1, which moved eleven coverage caps out: ten
to `convention`, one to `presentation`. 0.170.0 moved the crawl's page and depth caps to
`convention` and the MinHash pair to `presentation`; 0.172.0 moved the two crawl caps back,
since under `--sample` the cap still decided which pages a sampled verdict was about, and F11
(0.174.0) moved them to `convention` again once a sample drawn from a cut crawl withholds what the
cut could decide; its second batch moved five definitional or prioritisation numbers to
`convention` and twenty-three that feed only a field no item reads to `presentation` (held by
`tests/test_presentation_basis.py`); its third wrote the judgement over eleven content and URL
numbers that no standard or reachable corpus settles and measured a twelfth (KW-076's body
text now keeps every non-empty paragraph, against a labelled extraction benchmark), and the next measured a mobile viewport
width (MB-100 now fails a fixed width over 360 CSS pixels, not 390), measured the profile
detector as a whole, and wrote the judgement over the rest; its fourth found eight Search
Console numbers deciding only what is printed and wrote the multi-market blocker into the
three that decide a verdict, once KW-070 and GO-139 withhold over a full page of rows.
Nothing is unnamed — that took a gate — and the last, the profile detector's MIN_SCORE, was
measured and adopted at 5 by Anton's decision. The calibrations so
far show what closing one costs: each took a corpus, a method and a stated limitation.

`audit_reachability.py` proves 2 of the 145 script-backed assertions unable to report
FAIL and claims nothing about the other 143 either way. Proving more of them reachable is
this clause's other half.

### Clause 3 — the document says what the code does

The specification's ledger above is this clause's measure for behaviour. For prose the
gate is `tests/test_prose_counts.py`: every count this file, `README.md`, `plugin.json`,
`pyproject.toml`, `KNOWN-ISSUES.md`'s header and the census's own documentation state is
derived and compared. `tests/test_protocol_counts.py` holds the protocol's counts in
`SKILL.md` and the agents, and is the one derivation of every registry population both
modules read; no number is bound by both. It is narrower than the ask it answers. A sentence of the form
"X is N" outside those files, and a threshold named in prose, are still read by nobody.

---

## What 1.0 requires, in the order the numbers should move

1. **`inherited` 0 → 0**, done at 0.174.0 (F11): each number calibrated or relabelled with
   the judgement written out; `tests/test_inherited_basis.py` keeps the count from rising.
2. **REG-6's second reader** — the readings exist and are held against the registry;
   what would close the row is a check of whether each reading is true that is not the
   word of the person who wrote it.
3. **The 21 `partial` requirements and DEC-1**, each either held or narrowed to what is
   held.
4. **The 143 unclaimed assertions**, reduced by extending the detectors
   `audit_reachability.py` already has rather than by asserting reachability in prose.
5. **The census's 1 and 23**: the 23 each name the outside service or key they wait for
   (F06, 0.175.0); the 1, `SE-118`, needs the entry gate to answer it.
6. **Clause 3 beyond counts** — every checkable sentence in `SKILL.md`, `README.md` and
   this file tied to observable behaviour, the way counts now are.

Then the registry is declared stable and the cadence becomes external: the Public
Suffix List snapshot, Google's documented crawler list, the Core Web Vitals bands,
schema requirements. The tool changes when the web changes.

**Whether to declare 1.0 is Anton's decision**, and the only one here that is not
technical. `0.100.0` was chosen on 21 September to avoid making it by accident.

---

## Deliberately not built

**More checks.** 217 is already past what a client reads. Item 218 adds a line to a
document that gets skimmed; the releases since this was first written added almost none
and made the ones already there mean what they say.

**A link index or competitor data.** That is a data business, not a plugin. The refusal
to emit a toxicity score without a link index is the correct call and stays.

**Public distribution as a goal.** It should fall out of the above or not happen. Its
cost is not code — it is a standing obligation to triage other people's sites against a
tree of this size with one maintainer, at this project's own observed rate of roughly
one defect per three tests written.
