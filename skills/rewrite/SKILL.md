---
name: rewrite
description: Rewrite claudish text into plain natural language without changing its meaning. Use when asked to unclaudish, de-slop, simplify the register of, or plain-English a passage, file, or document.
argument-hint: [file path or pasted text]
allowed-tools: Read, Edit, Write, Bash
---

Rewrite the given text into plain natural language. The input is
$ARGUMENTS: a file path (rewrite the file in place unless told
otherwise) or pasted text (reply with the rewrite only).

## Rewrite rules

1. Recover the smallest set of ordinary statements that captures the
   full meaning. Several claudish sentences may become one plain one.
2. Rewrite at the lowest useful level of abstraction: "Only owners
   can merge", not "merge authority is restricted to the owner role".
3. Remove, without paraphrasing them: contrast framing ("not X, but
   Y"), staged emphasis ("the key insight", "honest take"), teasing
   pivots, aphoristic closers, praise, and significance flags. Do not
   replace them with filler; omit them.
4. Replace metaphors with literal statements: "gated on X" means X is
   required; "load-bearing" means essential; "landed" means merged or
   deployed. Keep a technical term when it is genuinely the clearest
   word (canonical, drift, race condition).
5. No em-dashes. Use commas, colons, parentheses, or a new sentence.
   En-dashes only in numeric or date ranges.
6. Turn nominalizations into verbs; prefer short complete sentences.

## Preserve meaning exactly

- Every fact, number, name, file path, condition, and stated
  uncertainty survives. Nothing gets stronger, weaker, broader, or
  narrower. "Not tested" must not become "incorrect"; "required"
  must not become "sufficient". Preserve the narrowest reading an
  ambiguous metaphor supports.
- Code blocks, inline code, identifiers, URLs, quoted text, YAML
  frontmatter, and markdown structure (headings, lists, tables,
  links) stay exactly as they are.

## Verify

After rewriting, check your work with the bundled scorer:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/claudish_core.py" < FILE

The rewrite's score should be lower than the original's, and its
verdict should be "pass". Exception: if a remaining violation sits
inside quoted text, code, or other content the fidelity rules forbid
changing, leave it as it is, say so, and treat the rewrite as done.
Then re-read the rewrite against the original and confirm every fact
survived; fix anything that drifted. Report the before and after
scores in one sentence.
