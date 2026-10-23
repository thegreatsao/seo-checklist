# Second reading: does each item's rule decide the question its title asks?

seo-checklist audits a website against a fixed registry of items. Each item has a **title**, the question a site
owner wants answered, and a **check**: a script (`check.script`, run with `check.args`) prints JSON, the value at
`check.assert.path` is tested by the assertion beside it, and that decides PASS or FAIL. `check.applies_when`, when
present, decides first whether the item applies at all (not applying is no verdict, not a pass); `check.warn` is a
softer band beside the assertion; `check.requires` says what input the script gets (`fetch`: one live page;
`offline`: one page's saved HTML; `crawl`: the crawled pages; `api`, `gsc`, `safe_browsing`: an outside service the
operator has keys for). Some items carry a **`measures`
sentence**, printed in the report beside the verdict, which says plainly what the check decides when it decides less
than the title asks.

You are reading each item cold: say whether its rule, as the script's source computes the asserted path, decides the
question its title asks.

## Blind pass

Below the instructions come the items — title, check, `measures` sentence or none — and then the source of every
script they run. The working directory is a copy of the plugin's `scripts/` folder: read the helper modules a script
imports there when its source alone does not show what a value means. Use nothing else: no other files, no search,
no network, and do not run anything.

Give each item one verdict:

- `answers` — the asserted path decides the title's question: on a site where the check applies, PASS means the site
  does what the title asks and FAIL means it does not, for the pages the check reads.
- `measures` — the rule decides a narrower or a different question than the title asks, and the item's `measures`
  sentence states accurately what it decides and where that falls short of the title. Only an item that carries a
  `measures` sentence can get this verdict.
- `owed` — neither: the rule decides something other than, or less than, the title asks, and no accurate `measures`
  sentence covers the gap. The item needs repair.

Ways a rule has failed its title before, each worth checking and none a verdict by itself:

- the title names something only an outside source holds (Search Console's index, other sites' links, rankings,
  uptime history), and the script reads only the site;
- an *at least one* assertion where the title asks about every image, link or page;
- a title joining two subjects (`&`, `and`, `/`, a parenthetical), where the rule reads one;
- a quality word (*meaningful*, *descriptive*, *sufficient*, *clear*, *optimized*…) that a rule can satisfy by mere
  presence;
- a path whose computation, in the source, counts something adjacent to what the title names.

Answer in exactly this form, one block per item, in the order given, and nothing else:

```
ITEM <the item's label>
VERDICT: answers | measures | owed
REASONS: <two to five sentences: what the asserted path counts, in the source's own terms with the function or
line that computes it, and why that does or does not decide the title>
```

## Open pass

You are now shown the first reading of items you judged above: its verdict, its reading (what its author says the
rule decides) and its answers to the shapes that fire on the item. Keep your own verdict as you gave it. Say, for each
item, whether the first reading gets anything wrong: a verdict you disagree with, a claim about what the script
computes that the source does not bear out, or a shape answer that does not answer its shape.

Answer in exactly this form, one block per item, in the order given, and nothing else:

```
ITEM <the item's label>
DISPUTE: none | <one to three sentences naming what the first reading gets wrong, citing the source>
```

## How this brief is run

Not sent to the reader. The blind prompt is this file up to `## Open pass` followed by
`audit_item_readings.py --blind ID ...`; the open prompt, sent by resuming the same Codex session, is the section
`## Open pass` followed by `audit_item_readings.py --open ID ...`. The run:
`codex exec -m gpt-6.1-sol -c model_reasoning_effort=high -s read-only --skip-git-repo-check -C <a copy of
skills/seo-checklist/scripts/> -o <answer file> - < <prompt file>`, then, from that same copy as the working directory, `codex exec resume
--skip-git-repo-check <session id> -m gpt-6.1-sol -c model_reasoning_effort=high -o <answer file> - < <open prompt
file>` (`resume` takes no `-C` or `-s`; the session keeps its read-only sandbox). The copy holds no readings, tests, docs or history. Each answer is entered by hand into
`item-readings.json` as the entry's `second_reading` (plan: `docs/sprint-20261023-F03-plan.md`): `reader` `codex
gpt-6.1-sol high`, `session` the Codex session id, `verdict` the blind verdict, `dispute` the open pass's when it is
not `none`, `read` from `audit_item_readings.py --digest ID`.
