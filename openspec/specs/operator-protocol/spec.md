# Operator protocol — what the tool guarantees, and what it can only ask of whoever drives it

## Purpose

What the agent driving this tool owes the person reading its output — the half of
`SKILL.md` that is an obligation on the operator rather than on the code.

This is the only capability in the suite whose reader is a person, and that is why six of
its eight requirements are unread rather than badly read. A test can watch a merge refuse
an answer; nothing can watch an operator quote a score without its share, or assemble an
answer from memory when the tool for it was absent. The requirements are written anyway,
because an obligation nobody wrote down is one nobody can be held to — and because the two
that *are* mechanisable, the marking and the counts, turned out to be the two that were
wrong.

**Capability:** the instructions to the agent or person running an audit, and the bundled
playbooks and judgement agents they invoke (C46, C47 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** what the report must show belongs to
[`openspec/specs/reporting/`](../reporting/spec.md); what a status means belongs to
[`openspec/specs/verdicts/`](../verdicts/spec.md); how a run is scoped and gated belongs to
[`openspec/specs/run-lifecycle/`](../run-lifecycle/spec.md). This document says what the *operator*
owes, which is the one thing the tool cannot enforce.

---

## 1. The only document whose reader is not a machine

Every other capability in this suite is code answering to code. This one is prose
addressed to whoever drives the tool — today, an agent — and its subject is the gap
between what the audit produces and what the person receiving it is told.

That gap is real and one-directional. The tool computes a score and a weight share; the
operator reports "96". The tool marks nine items as answered by a model; the operator says
"the audit found". The tool refuses to decide a competitor list without a search; the
operator, asked for competitors, can simply write some down. None of that is a defect in
the code, and none of it is visible in the artifact afterwards.

So the requirements here divide into two kinds, and **the division is the point of the
document**. Some obligations the tool can guarantee: it can refuse to print a score without
its share, it can force the private-host notice through `--quiet`, it can mark a model's
answer. Others only the operator can keep: quoting the share when they summarise, not
pasting an evidence string at a client, not answering a checklist item from memory. Today
these are interleaved in one file of 743 lines, addressed to one reader, with no marking of
which is which — which is the gap the capability inventory recorded as G21, and the reason
this document exists.

The distinction matters because the two need different remedies. An obligation on the tool
that is written as advice to the operator is a missing feature. An obligation on the
operator written as though the tool guaranteed it is a false assurance — and this suite has
now found the same shape in the code four times over, where a mechanism is guarded and the
list it runs over is not.

## 2. Who owes what

| obligation | tool can guarantee | operator must keep |
|---|---|---|
| the score appears with its weight share | in the renderers | when summarising in prose |
| the private-host notice survives `--quiet` | yes | reporting it as staging |
| a model's answer is marked | in the payload | saying so out loud |
| the sample size is stated | in the evidence | repeating it |
| an evidence string is never pasted at a client | no | yes |
| a checklist item is never answered from memory | no | yes |
| the model-judgement queue is run | no | yes |
| a playbook never moves a status | no | yes |

Six of the eight rows have no mechanical enforcement in their right-hand column, which is
the honest shape of this capability rather than a defect in it.

## Requirements

### Requirement: OPR-1 — the protocol says which obligations are the tool's and which are the operator's

Every instruction in the operator protocol SHALL be marked as one of two things: a
behaviour the tool guarantees, or a behaviour the operator must supply. A reader MUST be
able to tell, per line, which it is.

**Why:** an operator who believes the tool guarantees something it merely recommends will
stop checking. The failure is silent, delayed, and lands on a client — and the tool cannot
detect it, because from inside the run everything happened correctly.
**Reader:** **none.** The protocol is 743 lines of prose in one voice with no marking, and
no test reads it for this or anything else. Three test functions mention the file at all,
and all three are about the registry's relationship to it rather than its content.

#### Scenario: an instruction the tool guarantees
- **WHEN** the protocol states something the code does on its own
- **THEN** it is marked as such, and an operator does not spend effort ensuring it

#### Scenario: an instruction the operator must supply
- **WHEN** the protocol states something only a person can do
- **THEN** it is marked as such, and its absence is a gap in the audit rather than a bug

#### Scenario: one undifferentiated voice
- **WHEN** the document is written in a single register with no marking
- **THEN** a reader cannot tell a guarantee from an obligation, and will assume the
  reading that costs them least — which is the state the protocol is in today

### Requirement: OPR-2 — the score is never quoted without the share it covers

Wherever the operator states the score — in a summary, a message, a client email —
the proportion of the registry it was computed over SHALL go with it.

**Why:** this is `openspec/specs/reporting/` REP-1 restated for the human link in the chain, and it
is the one place the number escapes the tool's control entirely. "96" travels; "96, over
60% of the registry" does not travel as well and is the true one.
**Reader:** **none**, and unenforceable by construction — the tool cannot see what the
operator writes. The renderers print the pair, which is REP-1's `none` for a different
reason; here nothing is even in a position to check.

#### Scenario: the number leaves the tool
- **WHEN** an operator or an agent quotes the score anywhere outside the report
- **THEN** the share it covers is quoted with it

#### Scenario: a summary that rounds the caveat away
- **WHEN** a message says "the audit scored 69" and stops
- **THEN** the obligation is unmet, even though the tool's own surfaces were correct —
  which is why this requirement exists here rather than in `openspec/specs/reporting/`

### Requirement: OPR-3 — a claimed verdict is reported as claimed

Where the operator summarises results, an answer a model produced and an answer a
person asserted SHALL be described as such, and MUST NOT be folded into "the audit
found".

**Why:** the audit's authority rests on the reader being able to tell measurement from
judgement. The payload records who decided each item precisely so this is possible; a
summary that drops it spends the distinction the tool went to trouble to preserve.
**Reader:** **none.** The `decided_by` stamp exists and is asserted in the payload
(`openspec/specs/reporting/` REP-4); nothing reads what the operator does with it.

#### Scenario: a summary of mixed provenance
- **WHEN** some items were measured, some judged by a model and some claimed by a person
- **THEN** the summary says which is which

#### Scenario: everything becomes "the audit found"
- **WHEN** a claimed verdict is reported in the same voice as a measurement
- **THEN** the reader is given more confidence than the evidence supports, and the
  payload's own `decided_by` stamp was there to prevent exactly that

### Requirement: OPR-4 — the model-judgement queue is run, or the audit says it was not

Items awaiting model judgement SHALL be judged, or the operator MUST report the audit
as incomplete with the count outstanding.

**Why:** an unanswered queue caps the audit — those items are `LLM_PENDING`, out of the
scored set, and the score is a fraction of what remains. Reporting that number as the
result of a completed audit overstates coverage by exactly the size of the queue.
**Reader:** partial, on the tool's side only. The pending items appear in the payload's
waiting list and the renderers show them, so the *information* is present in every
artifact. Whether the operator acts on it is unread, and unreadable.

#### Scenario: the queue is run
- **WHEN** the model-judgement queue is answered and merged
- **THEN** the audit is complete in that respect

#### Scenario: the queue is skipped
- **WHEN** it is not run
- **THEN** the audit is reported as incomplete, with the number still outstanding
- **AND** a report that omits both the judgements and the fact of their absence reads as
  a finished audit

### Requirement: OPR-5 — a playbook never moves a status

The bundled playbooks tell an operator how to gather something. They MUST NOT decide
items, and following one is not evidence.

**Why:** a playbook is a procedure, and a procedure that could set a verdict would be a
checker written in prose and run by hand — with no evidence trail, no reproducibility and
no way for anybody to disagree with it.
**Reader:** **none.** The rule is stated in the playbooks themselves and nothing enforces
it. In practice it holds because a playbook has no mechanism to write a status; the rule
exists for the operator, who does.

#### Scenario: a playbook followed
- **WHEN** an operator works through a playbook
- **THEN** whatever they gathered may become evidence; the fact of having followed it
  may not

#### Scenario: a playbook cited as the answer
- **WHEN** an item is moved off its pending status because the procedure was performed
- **THEN** the requirement is violated: a procedure is a way of looking, not a thing
  seen

### Requirement: OPR-6 — no answer is fabricated when the tool for it is absent

Where an item requires a capability the operator does not have — a search tool, a
browser, a credential — the item SHALL be `N/A` with the absence as its evidence. An
answer assembled from memory MUST be refused.

**Why:** the competitor-research playbook states this better than a specification can: a
competitor list assembled from memory "is fabrication with a confident tone, and it is
worse than an honest N/A". The confident tone is the whole problem — it is indistinguishable
from a researched answer, and it is the failure mode an agent operator is most prone to.
**Reader:** **none.** The playbook instructs the operator to stop; nothing checks that they
did, and nothing could. This is the single most consequential unenforceable rule in the
suite, and writing it down is the only available remedy.

#### Scenario: the tool for the question is absent
- **WHEN** an item needs a search, a browser or a credential the operator does not have
- **THEN** the item is `N/A` and the evidence says which capability was missing

#### Scenario: an answer from memory
- **WHEN** an operator answers from what they already believe about the site or its
  competitors
- **THEN** the answer is refused
- **AND** it is indistinguishable from a real one once merged, which is why the rule has
  to bind before the answer is written rather than after

### Requirement: OPR-7 — a manual answer carries its evidence

An operator answering a `MANUAL` item SHALL supply what they looked at. An answer
without one MUST be refused.

**Why:** this is the one operator obligation the tool *can* enforce, and it does. It is
listed here rather than only in `openspec/specs/reporting/` because from the operator's side it is
the difference between recording a judgement and asserting one.
**Reader:** partial. The merge does refuse an answer with no stated reason and reports the
refusal by id — the behaviour `openspec/specs/reporting/` REP-5 specifies — so the rule is
implemented and not merely asked for. But that merge is the least-tested of the three, with
a single test function covering the one path in this whole capability that a person can
abuse, and nothing asserts that the refusal is visible to the operator who caused it.

#### Scenario: an answer with its evidence
- **WHEN** a person answers a `MANUAL` item and states what they examined
- **THEN** the answer is accepted and the evidence travels with the verdict

#### Scenario: an answer without
- **WHEN** the reason is empty or whitespace
- **THEN** the merge refuses it by id and prints the refusal, rather than accepting a
  verdict nobody can check

### Requirement: OPR-8 — the protocol's counts come from the registry

Where the protocol states how many items a queue produces, how many a person must
answer, or how a lens splits, that number SHALL be checked against the registry by a
gate that fails when the two disagree, and a count no gate reads MUST NOT appear in the
protocol at all.

**Why:** the protocol is what an agent reads before running anything, and a wrong count
there sets a wrong expectation for the whole run — an operator told to expect 33 model
verdicts who receives 38 will assume something went wrong, or worse, will not notice.

The sentence used to end "and MUST NOT be written into the prose", which is
unimplementable: a Markdown file cannot derive anything, and removing the numbers would
make the protocol worse for the reader it is written for. The harm the requirement was
built around is an *unheld* count, not a written one, so that is what it now forbids.

**Reader:** enforced. `tests/test_protocol_counts.py` holds it: each claim names a file,
a pattern that must match exactly once, and a population derived from `checklist.json`;
the match-once half runs first, because a pattern that has stopped matching makes every
assertion about it vacuously true. Two of the sweeps are mechanisms rather than lists —
the queue table and the lens agent files are generated from the set of lenses the
registry carries, so a new lens fails until its row and its agent exist. What is *not*
held is a count nobody entered in the ledger; that is `openspec/specs/governance/`
GOV-3's general absence, and it stands.

#### Scenario: the registry grows
- **WHEN** items are added or their source changes
- **THEN** every count the protocol states moves with the registry

#### Scenario: a count typed into a sentence with no gate behind it
- **WHEN** a number is written into the prose beside the thing it counts and nothing
  derives it
- **THEN** it is wrong within a release and nothing says so
- **AND** the operator plans their work from it, which is what makes this worse here
  than in a comment

#### Scenario: the sentence holding a count is reworded
- **WHEN** the prose around a checked number changes so the gate no longer finds it
- **THEN** the gate fails for that reason rather than passing on a match it did not
  make

## 4. Invariants

* **INV-O1** — every item the protocol tells an operator to answer by hand is an item the
  registry marks `manual`. *Reader:* **none.**
* **INV-O2** — every lens the protocol names has an agent file, and every agent file is
  named by the protocol. *Reader: partial* — a test asserts the queue filenames match the
  four lenses; the fifth agent file, the adversary, is named by the protocol and is not a
  lens, and nothing reconciles the two lists.
* **INV-O3** — a playbook names only items that exist in the registry. *Reader: enforced* —
  the playbook manifest's item ids are checked against the registry.
* **INV-O4** — no bundled playbook or agent file writes to the results.
  *Reader: enforced by construction* — they are prose files with no execution path; nothing
  asserts it, and nothing could execute them to find out.

## 5. What this document does not decide

* what the report shows — `openspec/specs/reporting/`;
* what a status means or who each names — `openspec/specs/verdicts/`;
* how the model-judgement queue is split or routed — `openspec/specs/reporting/` REP-11;
* how an agent should be evaluated or improved. The protocol is a contract, not a
  training document;
* whether an agent is the right operator at all. That is a product decision, and the
  protocol is written as though the answer is yes.

## 6. Open questions

**Should the protocol be split into two files?** OPR-1 requires the distinction to be
visible and does not require two documents. Two files — what the tool guarantees, what the
operator must supply — would make the distinction structural and unforgettable, and would
also split a document people read top to bottom. A marking convention inside one file is
cheaper and easier to let slip. What would settle it: whether the operator-side half is
long enough to stand alone, which is measurable and has not been measured.

**Can any operator obligation be made mechanical?** Six of the eight rows in §2 have no
enforcement, and the document treats that as a fact about the category. Two of them may not
be: the tool could refuse to emit a summary line without its share, and it could decline to
print an evidence string in a client-facing surface at all. Both move an operator obligation
into the tool, which is the only kind of progress available here. What would settle it:
whether operators actually copy from the surfaces the tool controls, or write their own.

**What does the protocol owe an operator who is not an agent?** It is written for one, and
the instructions that matter most — do not fabricate, do not paste raw evidence, say who
decided — are precisely the failure modes of a language model rather than of a person. A
human operator reading it meets a document about somebody else's weaknesses. What would
settle it: whether anyone other than an agent has run this tool.

## Appendix A — measured disagreements, 4 September 2026

Observation, not specification. Measured at commit `9408a4c`, registry `b0abf2819da0`.

#### A.1 — fourteen counts in the prose disagreed with the registry, by up to eight

Closed on 6 September 2026. Recorded in full because the shape of the miss is the useful
part: five were found by reading the document and nine more by writing the derivation
the reading said was needed.

| where | stated | registry |
|---|---|---|
| `SKILL.md` — "the LLM queue produces" | 33 | **38** |
| `SKILL.md` — "the model's" | 36 | **38** |
| `SKILL.md` — "a person has to look at" | 34 | **31** |
| `SKILL.md` — "thirty-four ticks would move" | 34 | **31** |
| `SKILL.md` — queue table, `copy` | 14 | **19** |
| `SKILL.md` — queue table, `layout` | 11 | **13** |
| `SKILL.md` — queue table, `market` | 2 | **3** |
| `checklist_runner.py` `score()` comment | "eight duplicate groups" | **7** |
| `checklist_runner.py` `score()` comment | "ten twins" | **9** |
| `checklist_report.py` `apply_llm_review()` docstring | "thirty items rest on" | **38** |
| `seo-llm-copy.md` — `description:` | 14 | **19** |
| `seo-llm-layout.md` — `description:` | 11 | **13** |
| `seo-llm-market.md` — `description:` | 2 | **3** |
| `seo-llm-market.md` — "Two items" | 2 | **3** |

The `apply_llm_review()` docstring is the largest and the one that mattered most: it is
the sentence explaining why a second reading exists, and it understated the exposure by
eight items — a fifth of the population it argues about. The nine unrecorded ones are
the more interesting half. Three of them sit in an agent file's `description:`, which is
what a host matches a task against, so a stale number there is read before the file is;
and the queue table is the thing an operator uses to decide how many agents to run.

Only `seo-llm-adversary.md` had it right, at thirty-eight, which is why the gate compares
values rather than spellings.

This was the seventh count in this tree found stating something the tree does not, after
the registry's own `source` string, two in the corpus README, two in the census
docstring, the shapes reference's account of itself, the guard's marker count and the
inventory's basis distribution. Every one has the same form, and
`openspec/specs/governance/` GOV-3 is the general rule they all violate — still unheld in
general, now held for these.

#### A.2 — the protocol has three mentions in the suite and none of them reads it

`SKILL.md` is named in three test functions, all in the registry tests, and all about
whether the registry and the protocol agree on structural facts rather than about the
protocol's content. Nothing reads its instructions, which is expected — they are addressed
to a reader that is not a test runner — and worth recording because it means every
requirement in §3 that is *about the document* rather than about the tool is unread by
construction, not by omission.

#### A.3 — the strongest rule in this capability is a sentence in a playbook

The competitor-research playbook says:

> **No search, no verdict.** If you did not actually look at a result set, CO-191 is `N/A`
> with "no search was run" as the evidence. A competitor list assembled from memory is
> fabrication with a confident tone, and it is worse than an honest N/A.

That is the clearest statement of the operator failure mode anywhere in this repository, it
is better than the requirement written from it, and it lives in a resource file rather than
in the protocol. It is recorded here because the pattern is worth noticing: the sharpest
rules in this tree are consistently found in the comment or the docstring nearest the thing
that went wrong, and consistently absent from the document that ought to own them.

## Appendix B — how much of this document is enforced

**Probed:** A.1's counts, by deriving each figure from the registry and grepping the
prose for the stated one — and then by writing that derivation as a gate, which found
nine more. The rest were derived by reading, since most of this capability has no
mechanical surface to probe.

| | requirements |
|---|---|
| **enforced** | OPR-8 |
| **partial** | OPR-4, OPR-7 |
| **none** | OPR-1, OPR-2, OPR-3, OPR-5, OPR-6 |
| **opposed** | — none |

Invariants: INV-O3 and INV-O4 enforced; INV-O2 partial; INV-O1 unread.

**One enforced, two partial, five unread, of eight.**

This was the only census in the suite with nothing enforced at all, and it was the one
that was not an indictment. Five of these eight requirements are obligations on a person
or an agent, and no test can hold them — OPR-2 cannot be enforced because the tool cannot
see what the operator writes; OPR-6 cannot be enforced because fabrication is
indistinguishable from work from the inside. Writing them down is the entire available
remedy, and it is why this document exists.

The two `partial` rows are the two where the tool does something and stops short. OPR-7 is
the sharpest: the one operator obligation the tool *can* enforce, guarding the one path a
person can abuse, and it has a single test function behind it.

Two of the six were different, and they were the ones to act on. OPR-8's counts could be
derived — "a gate comparing the protocol's numbers to the registry is a morning's work
and would have caught all five drifts" is what this appendix said, and it was a morning's
work, and it caught fourteen. OPR-1 is the other: its marking is a property of a
document, which `tests/test_specs.py` already demonstrates is testable, since this
suite's other eleven documents are read by a machine for exactly that kind of structural
obligation.

The rest are a boundary rather than a debt. Every specification eventually reaches the point
where the next reader is a person, and this document is where this one does. What it can do
is be honest about which line is which — which is OPR-1, and which is unread.
