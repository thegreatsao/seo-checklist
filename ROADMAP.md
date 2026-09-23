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
| requirements | 149 | across 12 documents |
| enforced | 121 | held by something that fails when the requirement is violated |
| partial | 23 | held for part of what the requirement says |
| unread | 1 | held by nothing — `declarations` DEC-1 |
| bounded | 4 | the subject is outside the program; no test could observe a violation |

The `partial` column is where the work is, and a count does not say how much of each row
is held — read the document. The largest single debt is `registry` REG-6: five items
measured something other than their titles, all five were repaired by 0.108.0, and every
one was found by a person reading a rule against its title. Nothing in the tree would
notice the sixth.

### Clause 1 — a verdict, or a stated reason there is none

`tests/census.json` records what every item answered across every tree this repository
can serve:

```
.venv/Scripts/python.exe tests/verdict_census.py --check tests/census.json
```

| | count | what it means |
|---|---|---|
| answered somewhere, never FAIL | 21 | a rule that cannot fail, or a case the corpus does not have |
| answered somewhere, never PASS | 3 | the mirror |
| never answered anywhere | 34 | mostly honest — Search Console, PageSpeed and Safe Browsing cannot answer offline |

The three that were never seen passing are `AR-158`, whose visible-breadcrumb half no
fixture carries; `GEO-006`, whose script reads the JSON-LD graph with no boundary; and,
since 0.110.0, `GO-138`, because the good fixture's sitemap lists a page its robots.txt
forbids and that is now an invalid URL. The passing path of `GO-138` is held by unit
tests; restoring a served one is a fixture decision.

### Clause 2 — every number measured or declared unmeasured

```
.venv/Scripts/python.exe skills/seo-checklist/tools/audit_thresholds.py
```

| basis | count |
|---|---|
| standard | 14 |
| measured | 11 |
| convention | 55 |
| inherited | 77 |
| no basis | 0 |
| **numbers a verdict depends on** | **157** |

**`inherited` at 77 of 157 is the largest single gap between this tree and 1.0,** and it
has grown: it was 75 of 144 at 0.87.1. Nothing is unnamed — that took a gate — but half
the numbers a verdict rests on are still numbers nobody here decided. The calibrations so
far show what closing one costs: each took a corpus, a method and a stated limitation.

`audit_reachability.py` proves 2 of the 145 script-backed assertions unable to report
FAIL and claims nothing about the other 143 either way. Proving more of them reachable is
this clause's other half.

### Clause 3 — the document says what the code does

The specification's ledger above is this clause's measure for behaviour. For prose the
gate is `tests/test_prose_counts.py`: every count this file, `README.md`, `plugin.json`,
`pyproject.toml`, `KNOWN-ISSUES.md`'s header and the census's own documentation state is
derived and compared. It is narrower than the ask it answers. A sentence of the form
"X is N" outside those files, and a threshold named in prose, are still read by nobody.

---

## What 1.0 requires, in the order the numbers should move

1. **`inherited` 77 → 0**, by calibration or by an honest relabel to `convention` with
   the judgement written out.
2. **REG-6's reader** — something that would have noticed any of the five items that
   measured the wrong thing. Until it exists, `partial` there is the honest word.
3. **The 23 `partial` requirements and DEC-1**, each either held or narrowed to what is
   held.
4. **The 143 unclaimed assertions**, reduced by extending the detectors
   `audit_reachability.py` already has rather than by asserting reachability in prose.
5. **The census's 21 and 34**, each turned into an answer or a named structural reason.
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
