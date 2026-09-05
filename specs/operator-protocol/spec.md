# Operator protocol — what the tool guarantees, and what it can only ask of whoever drives it

**Capability:** the instructions to the agent or person running an audit, and the bundled
playbooks and judgement agents they invoke (C46, C47 of the capability inventory).

This document is normative and is written as though no code existed. Where the
implementation disagrees, the implementation is presumed wrong until this document is
changed by argument. Appendix A records disagreements measured on 4 September 2026.

Every requirement carries a **Reader** line naming what makes it fail when violated;
Appendix B is the census of those lines. A requirement whose reader is `none` is an
intention, and is counted as one.

**Inherited, not restated:** what the report must show belongs to
[`specs/reporting/`](../reporting/spec.md); what a status means belongs to
[`specs/verdicts/`](../verdicts/spec.md); how a run is scoped and gated belongs to
[`specs/run-lifecycle/`](../run-lifecycle/spec.md). This document says what the *operator*
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

## 3. Requirements

### OPR-1 — the protocol says which obligations are the tool's and which are the operator's

Every instruction in the operator protocol is marked as one of two things: a behaviour the
tool guarantees, or a behaviour the operator must supply. A reader must be able to tell,
per line, which it is.

**Why:** an operator who believes the tool guarantees something it merely recommends will
stop checking. The failure is silent, delayed, and lands on a client — and the tool cannot
detect it, because from inside the run everything happened correctly.
**Reader:** **none.** The protocol is 743 lines of prose in one voice with no marking, and
no test reads it for this or anything else. Three test functions mention the file at all,
and all three are about the registry's relationship to it rather than its content.

### OPR-2 — the score is never quoted without the share it covers

Wherever the operator states the score — in a summary, a message, a client email — the
proportion of the registry it was computed over goes with it.

**Why:** this is `specs/reporting/` REP-1 restated for the human link in the chain, and it
is the one place the number escapes the tool's control entirely. "96" travels; "96, over
60% of the registry" does not travel as well and is the true one.
**Reader:** **none**, and unenforceable by construction — the tool cannot see what the
operator writes. The renderers print the pair, which is REP-1's `none` for a different
reason; here nothing is even in a position to check.

### OPR-3 — a claimed verdict is reported as claimed

Where the operator summarises results, an answer a model produced and an answer a person
asserted are described as such, not folded into "the audit found".

**Why:** the audit's authority rests on the reader being able to tell measurement from
judgement. The payload records who decided each item precisely so this is possible; a
summary that drops it spends the distinction the tool went to trouble to preserve.
**Reader:** **none.** The `decided_by` stamp exists and is asserted in the payload
(`specs/reporting/` REP-4); nothing reads what the operator does with it.

### OPR-4 — the model-judgement queue is run, or the audit says it was not

Items awaiting model judgement are judged, or the operator reports the audit as incomplete
with the count outstanding.

**Why:** an unanswered queue caps the audit — those items are `LLM_PENDING`, out of the
scored set, and the score is a fraction of what remains. Reporting that number as the
result of a completed audit overstates coverage by exactly the size of the queue.
**Reader:** partial, on the tool's side only. The pending items appear in the payload's
waiting list and the renderers show them, so the *information* is present in every
artifact. Whether the operator acts on it is unread, and unreadable.

### OPR-5 — a playbook never moves a status

The bundled playbooks tell an operator how to gather something. They do not decide items,
and following one is not evidence.

**Why:** a playbook is a procedure, and a procedure that could set a verdict would be a
checker written in prose and run by hand — with no evidence trail, no reproducibility and
no way for anybody to disagree with it.
**Reader:** **none.** The rule is stated in the playbooks themselves and nothing enforces
it. In practice it holds because a playbook has no mechanism to write a status; the rule
exists for the operator, who does.

### OPR-6 — no answer is fabricated when the tool for it is absent

Where an item requires a capability the operator does not have — a search tool, a browser,
a credential — the item is `N/A` with the absence as its evidence. An answer assembled from
memory is refused.

**Why:** the competitor-research playbook states this better than a specification can: a
competitor list assembled from memory "is fabrication with a confident tone, and it is
worse than an honest N/A". The confident tone is the whole problem — it is indistinguishable
from a researched answer, and it is the failure mode an agent operator is most prone to.
**Reader:** **none.** The playbook instructs the operator to stop; nothing checks that they
did, and nothing could. This is the single most consequential unenforceable rule in the
suite, and writing it down is the only available remedy.

### OPR-7 — a manual answer carries its evidence

An operator answering a `MANUAL` item supplies what they looked at. An answer without one
is refused.

**Why:** this is the one operator obligation the tool *can* enforce, and it does. It is
listed here rather than only in `specs/reporting/` because from the operator's side it is
the difference between recording a judgement and asserting one.
**Reader:** partial. The merge does refuse an answer with no stated reason and reports the
refusal by id — the behaviour `specs/reporting/` REP-5 specifies — so the rule is
implemented and not merely asked for. But that merge is the least-tested of the three, with
a single test function covering the one path in this whole capability that a person can
abuse, and nothing asserts that the refusal is visible to the operator who caused it.

### OPR-8 — the protocol's counts come from the registry

Where the protocol states how many items a queue produces, how many a person must answer,
or how a lens splits, those numbers are derived from the registry rather than written into
the prose.

**Why:** the protocol is what an agent reads before running anything, and a wrong count
there sets a wrong expectation for the whole run — an operator told to expect 33 model
verdicts who receives 38 will assume something went wrong, or worse, will not notice.
**Reader:** **none**, and five counts are wrong today (Appendix A.1), the largest by eight.
No gate compares prose to the registry, which is the same absence
`specs/governance/` GOV-3 states in general.

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

* what the report shows — `specs/reporting/`;
* what a status means or who each names — `specs/verdicts/`;
* how the model-judgement queue is split or routed — `specs/reporting/` REP-11;
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

### A.1 — five counts in the prose disagree with the registry, by up to eight

| where | states | registry |
|---|---|---|
| `SKILL.md` — "the LLM queue produces" | 33 | **38** |
| `SKILL.md` — "the model's" | 36 | **38** |
| `SKILL.md` — "a person has to look at" | 34 | **31** |
| `checklist_runner.py` `score()` docstring | "eight duplicate groups … ten twins" | **9 twins** |
| `checklist_report.py` `apply_llm_review()` docstring | "thirty items rest on one model's reading" | **38** |

The last is the largest and the one that matters most: it is the sentence explaining why a
second reading exists, and it understates the exposure by eight items — a fifth of the
population it is arguing about.

No gate compares prose to the registry. This is the seventh count in this tree found
stating something the tree does not, after the registry's own `source` string, two in the
corpus README, two in the census docstring, the shapes reference's account of itself, the
guard's marker count and the inventory's basis distribution. Every one has the same form,
and `specs/governance/` GOV-3 is the general rule they all violate.

### A.2 — the protocol has three mentions in the suite and none of them reads it

`SKILL.md` is named in three test functions, all in the registry tests, and all about
whether the registry and the protocol agree on structural facts rather than about the
protocol's content. Nothing reads its instructions, which is expected — they are addressed
to a reader that is not a test runner — and worth recording because it means every
requirement in §3 that is *about the document* rather than about the tool is unread by
construction, not by omission.

### A.3 — the strongest rule in this capability is a sentence in a playbook

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

**Probed:** A.1's five counts, by deriving each figure from the registry and grepping the
prose for the stated one. The rest were derived by reading, since most of this capability
has no mechanical surface to probe.

| | requirements |
|---|---|
| **enforced** | — none |
| **partial** | OPR-4, OPR-7 |
| **none** | OPR-1, OPR-2, OPR-3, OPR-5, OPR-6, OPR-8 |
| **opposed** | — none |

Invariants: INV-O3 and INV-O4 enforced; INV-O2 partial; INV-O1 unread.

**Nothing fully enforced, two partial, six unread, of eight.**

Nothing enforced is the worst census in the suite, matched only by `specs/scoring/`, and it
is the only one that is not an indictment. Six of these eight requirements are obligations
on a person or an agent, and no test can hold them — OPR-2 cannot be enforced because the
tool cannot see what the operator writes; OPR-6 cannot be enforced because fabrication is
indistinguishable from work from the inside. Writing them down is the entire available
remedy, and it is why this document exists.

The two `partial` rows are the two where the tool does something and stops short. OPR-7 is
the sharpest: the one operator obligation the tool *can* enforce, guarding the one path a
person can abuse, and it has a single test function behind it.

Two of the six are different, and they are the ones to act on. OPR-8's counts could be
derived — a gate comparing the protocol's numbers to the registry is a morning's work and
would have caught all five drifts. And OPR-1's marking is a property of a document, which
`tests/test_specs.py` already demonstrates is testable: this suite's other eleven documents
are read by a machine for exactly that kind of structural obligation.

The rest are a boundary rather than a debt. Every specification eventually reaches the point
where the next reader is a person, and this document is where this one does. What it can do
is be honest about which line is which — which is OPR-1, and which is unread.
