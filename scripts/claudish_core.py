"""Shared claudish-detection engine.

One lexicon, two consumers:
- The Stop-hook linter (lint_stop.py) evaluates the HARD tier only and
  blocks; hard patterns must have near-zero false positives.
- The scoring harness (claudish_score.py) evaluates every tier and
  produces a composite "claudish score" for evals.

Python 3 stdlib only. The em dash is always written as the escape
sequence backslash-u2014, never as a literal character, so this
source file contains none.
"""

import json
import re
import statistics

EM_DASH = "\u2014"

# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"\A---\n.*?\n(?:---|\.\.\.)\n", re.S)
FENCE_OPEN_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
DISPLAY_MATH_RE = re.compile(r"\$\$.*?\$\$", re.S)
INLINE_CODE_RE = re.compile(r"``(?:[^`]|`(?!`))+``|`[^`\n]+`")
BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DETAILS_TAG_RE = re.compile(r"</?(?:details|summary)[^>]*>")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK_RE = re.compile(r"\[[^\]]{0,200}\]\([^)\s]*\)")
LINK_TARGET_RE = re.compile(r"\]\([^)\s]+\)")
# Diff bodies and code-looking indented lines are not prose.
DIFF_LINE_RE = re.compile(
    r"^(?:[+-](?=\S)|@@ |diff --git|index [0-9a-f])")
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")
CODEISH_RE = re.compile(r"[={}();`\\]|\bdef\b|\breturn\b")
URL_RE = re.compile(r"https?://\S+")
# Short quoted spans are mentions, not the writer's own voice
# ("the linter bans \"here's the thing\"" must not flag).
QUOTED_SPAN_RE = re.compile("\"[^\"]{1,300}\"|“[^”]{1,300}”")
HEADING_MARK_RE = re.compile(r"^#{1,6}\s+")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*\s*$")


def _strip_fenced_code(text):
    """Remove fenced code blocks with CommonMark close rules.

    An unclosed fence at EOF swallows the remainder (truncation
    safety: streamed text must never leak code into prose metrics).
    """
    kept_lines = []
    fence_char = None
    fence_len = 0
    for line in text.split("\n"):
        open_match = FENCE_OPEN_RE.match(line)
        if fence_char is None:
            if open_match:
                marker = open_match.group(1)
                fence_char = marker[0]
                fence_len = len(marker)
            else:
                kept_lines.append(line)
        else:
            if (open_match and open_match.group(1)[0] == fence_char
                    and len(open_match.group(1)) >= fence_len
                    and line.strip() == open_match.group(1)):
                fence_char = None
    return "\n".join(kept_lines)


def _is_table_line(line):
    return line.count("|") >= 2 or TABLE_SEP_RE.match(line)


def preprocess(text):
    """Return (phrase_corpus, sentence_corpus, prose_chars)."""
    working = FRONTMATTER_RE.sub("", text)
    working = _strip_fenced_code(working)
    working = DISPLAY_MATH_RE.sub(" ", working)
    working = INLINE_CODE_RE.sub(" CODE ", working)
    working = HTML_COMMENT_RE.sub(" ", working)
    working = DETAILS_TAG_RE.sub(" ", working)
    working = IMAGE_RE.sub(" ", working)
    working = MD_LINK_RE.sub(" LINK ", working)
    working = URL_RE.sub(" ", working)
    working = LINK_TARGET_RE.sub("]", working)
    working = QUOTED_SPAN_RE.sub(" QUOTE ", working)

    phrase_lines = []
    sentence_lines = []
    for line in working.split("\n"):
        if BLOCKQUOTE_RE.match(line) or _is_table_line(line):
            continue
        if DIFF_LINE_RE.match(line):
            continue
        if INDENTED_CODE_RE.match(line) and CODEISH_RE.search(line):
            continue
        is_heading = bool(HEADING_MARK_RE.match(line))
        is_list_item = bool(LIST_ITEM_RE.match(line))
        clean = HEADING_MARK_RE.sub("", line)
        phrase_lines.append(clean)
        if not is_heading and not is_list_item:
            sentence_lines.append(clean)

    # Curly apostrophes must match straight-apostrophe patterns.
    phrase_corpus = "\n".join(phrase_lines).replace("’", "'")
    sentence_corpus = "\n".join(sentence_lines).replace("’", "'")
    prose_chars = len(re.sub(r"\s+", " ", phrase_corpus).strip())
    return phrase_corpus, sentence_corpus, prose_chars


# Sentence splitting with abbreviation and number protection.
ABBREV_RE = re.compile(
    r"\b(e\.g\.|i\.e\.|etc\.|vs\.|cf\.|Dr\.|Mr\.|Ms\.|approx\."
    r"|v\d+(?:\.\d+)+|\d+\.\d+)",
    re.I,
)
SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s+|$)")


def split_sentences(text):
    protected = ABBREV_RE.sub(lambda m: m.group(0).replace(".", "\x00"), text)
    parts = SENTENCE_SPLIT_RE.split(protected)
    sentences = []
    for part in parts:
        restored = part.replace("\x00", ".").strip()
        if restored:
            sentences.append(restored)
    return sentences


def is_mostly_english(text):
    """Skip phrase metrics on mostly non-English prose."""
    letters = re.findall(r"[^\W\d_]", text)
    if not letters:
        return True
    ascii_letters = [c for c in letters if c.isascii()]
    return len(ascii_letters) / len(letters) >= 0.6


# ---------------------------------------------------------------------------
# Regex metrics
# ---------------------------------------------------------------------------
# Each entry: id, tier ('hard'|'soft'), weight, cap, pattern, and
# optional flags. 'flat' metrics contribute points directly instead of
# a length-normalized rate. 'anchored' metrics run against the raw
# message start rather than the corpus.

REGEX_METRICS = [
    # --- HARD TIER (blocking) ---
    {
        "id": "em_dash",
        "tier": "hard",
        "weight": 5.0,
        "cap": 4.0,
        "pattern": re.compile(
            "(?<=[^\\n])[\u2014\u2E3A\u2E3B]|(?<=[A-Za-z]) \u2013 (?=[A-Za-z])"
        ),
        "advice": "replace the dash with a comma, colon, or new sentence",
    },
    {
        "id": "syco_opener",
        "tier": "hard",
        "flat": 10.0,
        "anchored": True,
        "pattern": re.compile(
            r"\A\s*(?:you(?:'re| are) "
            r"(?:absolutely|completely|totally) (?:right|correct)"
            r"|great (?:question|catch|point)"
            r"|excellent (?:question|point)"
            r"|perfect)(?=\s*(?:[.!,:;]|\n|$))",
            re.I,
        ),
        "advice": "start with the substance, not praise or agreement",
    },
    {
        "id": "syco_anywhere",
        "tier": "hard",
        "weight": 6.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\byou(?:'re| are) (?:absolutely|completely) "
            r"(?:right|correct)\b",
            re.I,
        ),
        "exclude": re.compile(
            r"\b(?:even if|if|unless|suppose|supposing|assuming"
            r"|whether|when)\b[^.!?\n]{0,30}you(?:'re| are)",
            re.I,
        ),
        "advice": "drop the flattery; state the corrected fact directly",
    },
    {
        "id": "heres_the_thing",
        "tier": "hard",
        "weight": 4.0,
        "cap": 3.0,
        "pattern": re.compile(r"\bhere's the thing\b", re.I),
        "advice": "delete the pivot phrase and state the point",
    },
    {
        "id": "worth_noting",
        "tier": "hard",
        "weight": 3.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\b(?:it's|it is) (?:worth noting|worth mentioning"
            r"|important to note)\b|\bworth noting:",
            re.I,
        ),
        "advice": "delete the preamble; if it matters, just say it",
    },
    {
        "id": "crucially",
        "tier": "hard",
        "weight": 3.0,
        "cap": 3.0,
        "pattern": re.compile(r"(?:\A|[.!?:]\s+|\n\s*)crucially,", re.I),
        "advice": "delete the significance flag; the fact can stand alone",
    },
    {
        "id": "delve",
        "tier": "hard",
        "weight": 4.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bdelv(?:e|es|ed|ing)\s+(?:into|deeper|further)\b", re.I
        ),
        "advice": "use a plain verb: look at, examine, read",
    },
    # --- SOFT TIER (scoring only) ---
    {
        # Bare conjugations of delve; excludes the Go debugger Delve,
        # the surname Delves, and other capitalized proper-noun uses.
        "id": "delve_bare",
        "tier": "soft",
        "weight": 2.0,
        "cap": 3.0,
        "pattern": re.compile(r"\bdelv(?:e|es|ed|ing)\b", re.I),
        "exclude": re.compile(
            r"Delves?\b|go-delve|\bdlv\b|debugger", ),
    },
    {
        # Ships soft until it proves zero false positives on a real
        # transcript corpus (promotion rule in PLAN.md 4.1).
        "id": "not_x_but_y_strict",
        "tier": "soft",
        "weight": 5.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\b(?:is|are|was|were)n't (?:just|only|merely|simply|about) "
            r"[^.!?\n]{1,40}[;,.]\s?(?:it|that|this)'s\b",
            re.I,
        ),
    },
    {
        "id": "not_x_but_y_loose",
        "tier": "soft",
        "weight": 3.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bnot (?:just|only|merely|simply) [^.!?\n]{1,60}"
            r"\b(?:but|rather|it's)\b"
            r"|\bisn't about [^.!?\n]{1,50}\.\s*it's about\b"
            r"|\bthe (?:real |key )?(?:question|problem|issue|point) isn't\b"
            r"|\bstops being [^.!?\n]{1,40} and (?:starts|becomes)\b",
            re.I,
        ),
    },
    {
        "id": "significance_flags",
        "tier": "soft",
        "weight": 1.5,
        "cap": 3.0,
        "pattern": re.compile(
            r"(?:\A|[.!?:]\s+|\n\s*)(?:importantly|notably|critically"
            r"|interestingly|remarkably|significantly),"
            r"|\bkeep in mind\b"
            r"|\bit's important to (?:understand|remember|realize)\b"
            r"|\bkey (?:takeaway|insight)\b"
            r"|\bthe key (?:thing|point) (?:here )?is\b",
            re.I,
        ),
    },
    {
        "id": "jargon",
        "tier": "soft",
        "weight": 1.0,
        "cap": 5.0,
        "pattern": re.compile(
            r"\bload-bearing\b|\bfootguns?\b|\bblast radius\b"
            r"|\bbattle-tested\b|\bfirst-class citizen\b|\btable stakes\b"
            r"|\bnorth star\b|\bsilver bullet\b|\bsharp edges\b"
            r"|\bgame-chang\w+\b|\bthe \w+ landscape\b|\byour \w+ journey\b"
            r"|\bdouble-click on\b|\btapestry\b"
            r"|\bseamless(?:ly)?\b|\bleverag(?:e|es|ed|ing)\b",
            re.I,
        ),
    },
    {
        # Context-gated engineering verbs: only rhetorical uses count.
        "id": "jargon_gated",
        "tier": "soft",
        "weight": 1.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bgated\b(?!\s+(?:on|by|behind)\b)"
            r"|\bsurfaced\b"
            r"|(?<!pr )(?<!patch )(?<!commit )(?<!change )\blanded\b"
            r"(?! (?:on|in) (?:main|master|trunk))",
            re.I,
        ),
        "exclude": re.compile(r"Surface[sd]?\b"),
    },
    {
        # Trailing appositive contrast: "goes down, not up." /
        # "a tuning task, not a design risk."
        "id": "contrast_appositive",
        "tier": "soft",
        "weight": 1.0,
        "cap": 4.0,
        "pattern": re.compile(
            r",\s(?:not|never|no longer)\s[^.!?\n,]{2,40}[.!?]", re.I
        ),
    },
    {
        # Staged emphasis with a colon reveal: "The strongest
        # argument here:" / "The one thing to watch:".
        "id": "staged_emphasis",
        "tier": "soft",
        "weight": 2.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bthe (?:strongest|real|key|core|crucial|important"
            r"|interesting|surprising|honest) "
            r"(?:argument|point|thing|question|insight|part|risk"
            r"|takeaway|answer|catch)(?: here)?(?: is)?:"
            r"|\bthe one thing to (?:watch|note|remember)\b",
            re.I,
        ),
    },
    {
        # Approved term expansion (field guide, 2026-08-25):
        # authenticity adjectives in their claudish frames only.
        "id": "authenticity_adj",
        "tier": "soft",
        "weight": 1.5,
        "cap": 4.0,
        "pattern": re.compile(
            r"\bthe real (?:problem|issue|question|fix|risk|challenge"
            r"|reason|work|win|cost|value|test)\b"
            r"|\ba real (?:issue|problem|risk|bug|win|concern)\b"
            r"|\bone (?:real|honest|genuine) \w+"
            r"|\ba genuine (?:issue|bug|risk|question|improvement|win)\b"
            r"|\bgenuinely (?:hard|difficult|useful|good|great|impressive"
            r"|ambiguous|unsure|uncertain|happy|novel|distinct|better)\b"
            r"|\bhonest (?:take|answer|assessment|caveat|question)\b"
            r"|\bhonestly[,?]"
            r"|\bwhat's actually happening\b"
            r"|\bthe actual (?:fix|problem|issue|behavior|cause|job)\b"
            r"|\bactually works\b",
            re.I,
        ),
    },
    {
        # Craft-praise adjectives; excludes verifiable tool facts
        # (clean build, merges cleanly) and math terms (proper subset).
        "id": "craft_adj",
        "tier": "soft",
        "weight": 1.0,
        "cap": 4.0,
        "pattern": re.compile(
            r"\bclean (?:fix|separation|abstraction|solution|design"
            r"|approach|architecture|api|interface|break)\b"
            r"|\bthe clean(?:est)? (?:way|fix|option|approach)\b"
            r"|\bsolid (?:plan|approach|foundation|choice|option"
            r"|coverage|start)\b"
            r"|\bsurgical\b|\btargeted fix\b|\bbattle-tested\b"
            r"|\bbulletproof\b|\bproduction-ready\b"
            r"|\bbelt-and-suspenders\b|\bnon-?trivial\b|\bcrisp\b"
            r"|\bproper(?:ly)?\b",
            re.I,
        ),
        "exclude": re.compile(
            r"proper (?:noun|subset|superset|fraction)", re.I),
    },
    {
        # Verdict verbs and evaluative frames.
        "id": "verdict_verbs",
        "tier": "soft",
        "weight": 1.0,
        "cap": 4.0,
        "pattern": re.compile(
            r"\bholds? up\b"
            r"|\bsurviv(?:es|ed) (?:scrutiny|contact|review)\b"
            r"|\bclears? the (?:bar|review)\b|\bfalls? over\b"
            r"|\bdoes the right thing\b|\bjust works\b"
            r"|\bheavy lifting\b|\bdoing a lot of (?:the )?work\b"
            r"|\bbuys? (?:you|us)\b|\bwins (?:outright|here)\b"
            r"|\breads as\b|\bsmells like\b"
            r"|\bearns its (?:place|keep)\b|\bthe unlock\b"
            r"|\bnorth star\b|\bsmoking gun\b"
            r"|\bwhich is exactly\b",
            re.I,
        ),
    },
    {
        # Adverb-first quiet failure drama ("silently drops"); the
        # standard term "fails silently" stays legitimate.
        "id": "quiet_verbs",
        "tier": "soft",
        "weight": 1.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\b(?:quietly|silently) (?:break|breaks|fail|fails|drop"
            r"|drops|ignore|ignores|swallow|swallows|corrupt|corrupts"
            r"|stops?|dies?|lies|lying)\b",
            re.I,
        ),
    },
    {
        # Wiring metaphor for code assembly.
        "id": "wiring_metaphor",
        "tier": "soft",
        "weight": 1.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bwiring\b|\bwired? (?:up|in|into|through)\b", re.I),
    },
    {
        # Process residue: the artifact narrating its own construction.
        # Validated against a labeled corpus before shipping; scored
        # only, since audience decides (a changelog may say "fixed").
        "id": "residue_archaeology",
        "tier": "soft",
        "weight": 2.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bsince-fixed\b"
            r"|\ball (?:\d+ )?(?:\w+ )?(?:bugs?|findings?|issues?) "
            r"(?:were )?fixed\b"
            r"|\bfindings? (?:hunted|confirmed)\b"
            r"|\bre-ran? (?:after|once) (?:we|I|the)\b"
            r"|\b(?:fix(?:ed|es)?|patched) "
            r"(?:mid|during)[- ](?:test|eval|review|development)\b"
            r"|\b(?:was|were) (?:contaminated|invalidated) by\b"
            r"|\badversarial review\b",
            re.I,
        ),
    },
    {
        "id": "residue_verification",
        "tier": "soft",
        "weight": 1.5,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bverified end[- ]to[- ]end\b"
            r"|\ball (?:tests? )?green\b"
            r"|\btested and (?:working|verified|confirmed)\b"
            r"|\b(?:thoroughly|extensively|rigorously) "
            r"(?:tested|validated|reviewed)\b"
            r"|\bverified on \d+ runs?\b",
            re.I,
        ),
    },
    {
        "id": "residue_machinery",
        "tier": "soft",
        "weight": 1.5,
        "cap": 3.0,
        "pattern": re.compile(
            r"\bjudge panel\b"
            r"|\b(?:spawned|fanned out) \d+ (?:agents?|workers?)\b"
            r"|\bthe (?:workflow|subagent|orchestrator) "
            r"(?:ran|completed|returned|found)\b"
            r"|\b(?:an?|the) agents? "
            r"(?:found|flagged|confirmed|hunted)\b",
            re.I,
        ),
    },
    {
        "id": "rhetorical_pivot",
        "tier": "soft",
        "weight": 1.0,
        "cap": 3.0,
        "pattern": re.compile(
            r"\?\s+(?:yes|no|because|it depends)\b"
            r"|\bwhich (?:raises|begs) the question\b"
            r"|\bthe kicker\b|\blet that sink in\b|\bfull stop\b",
            re.I,
        ),
    },
    {
        "id": "hedged_pair",
        "tier": "soft",
        "weight": 1.0,
        "cap": 2.0,
        "pattern": re.compile(
            r"\bsimple yet powerful\b|\bcomprehensive and thorough\b"
            r"|\bfast and reliable\b|\bclean and maintainable\b"
            r"|\brobust and scalable\b",
            re.I,
        ),
    },
    {
        "id": "triads",
        "tier": "soft",
        "weight": 0.5,
        "cap": 4.0,
        "pattern": re.compile(r"\b\w+, \w+, and \w+\b"),
    },
    {
        "id": "lets_opener",
        "tier": "soft",
        "flat": 2.0,
        "anchored": True,
        "pattern": re.compile(r"\A\s*let's\b", re.I),
    },
]


# ---------------------------------------------------------------------------
# Algorithmic soft metrics
# ---------------------------------------------------------------------------

def _staccato_points(sentences):
    """+4 per run of >= 3 consecutive sentences of <= 4 words."""
    points = 0.0
    run = 0
    for sentence in sentences:
        if len(sentence.split()) <= 4:
            run += 1
        else:
            if run >= 3:
                points += 4.0
            run = 0
    if run >= 3:
        points += 4.0
    return points


def _uniformity_points(sentences):
    """Penalize suspiciously uniform sentence lengths."""
    if len(sentences) < 8:
        return 0.0
    word_counts = [len(s.split()) for s in sentences]
    mean = statistics.mean(word_counts)
    if mean == 0:
        return 0.0
    cv = statistics.pstdev(word_counts) / mean
    return min(5.0, max(0.0, (0.35 - cv) * 10))


def _aphoristic_closer_points(phrase_corpus):
    paragraphs = [p.strip() for p in phrase_corpus.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return 0.0  # a closer needs something before it to close
    final = paragraphs[-1]
    if final.endswith("?"):
        return 0.0  # a follow-up offer is an invitation, not an aphorism
    if len(final) > 90 or "`" in final or re.search(r"\d", final):
        return 0.0
    if len(split_sentences(final)) != 1:
        return 0.0
    starts_like_verdict = bool(
        re.match(r"\A(?:That's |This is |The |And |So |No )", final)
    )
    short_and_punchy = len(final.split()) <= 8 and "," not in final
    return 3.0 if (starts_like_verdict or short_and_punchy) else 0.0


def _bold_term_list_points(text):
    """+2 per block of >= 3 '**Term:** explanation' list items."""
    # Matches '**Term:** text', '**Term**: text', and the full-bold
    # lead-sentence form '**Term is a non-issue.** text'.
    pattern = re.compile(
        r"^\s*(?:[-*+]|\d+[.)])\s+\*\*[^*]{2,60}?(?:[:.]\*\*|\*\*[:.])"
    )
    points = 0.0
    run = 0
    for line in text.split("\n"):
        if pattern.match(line):
            run += 1
        else:
            if run >= 3:
                points += 2.0
            run = 0
    if run >= 3:
        points += 2.0
    return points


def _exclaim_points(phrase_corpus):
    count = len(re.findall(r"!(?!\[)", phrase_corpus))
    return 0.5 * max(0, count - 1)


ALGO_METRICS = [
    {"id": "staccato", "tier": "soft"},
    {"id": "uniformity", "tier": "soft"},
    {"id": "aphoristic_closer", "tier": "soft"},
    {"id": "bold_term_list", "tier": "soft"},
    {"id": "exclaim", "tier": "soft"},
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

MIN_PROSE_CHARS = 200


QUOTE_CHARS = "\"'“”‘’`"


def _is_mention(corpus, match):
    return match.start() > 0 and corpus[match.start() - 1] in QUOTE_CHARS


def _find_snippets(pattern, corpus, exclude=None, limit=5):
    snippets = []
    for match in pattern.finditer(corpus):
        if _is_mention(corpus, match):
            continue
        if exclude is not None:
            window = corpus[max(0, match.start() - 45):match.end() + 25]
            if exclude.search(window):
                continue
        start = max(0, match.start() - 15)
        end = min(len(corpus), match.end() + 25)
        snippet = re.sub(r"\s+", " ", corpus[start:end]).strip()
        snippets.append(snippet[:80])
        if len(snippets) >= limit:
            break
    return snippets


def _count_matches(pattern, corpus, exclude=None):
    count = 0
    for match in pattern.finditer(corpus):
        if _is_mention(corpus, match):
            continue
        if exclude is not None:
            window = corpus[max(0, match.start() - 45):match.end() + 25]
            if exclude.search(window):
                continue
        count += 1
    return count


def evaluate(text, tiers=("hard", "soft")):
    """Score text. Returns the full result dict (see PLAN.md 4.1)."""
    phrase_corpus, sentence_corpus, prose_chars = preprocess(text)
    sentences = split_sentences(sentence_corpus)
    short_sample = prose_chars < MIN_PROSE_CHARS
    english = is_mostly_english(phrase_corpus)

    metrics = {}
    hard_violations = []
    score = 0.0

    for spec in REGEX_METRICS:
        if spec["tier"] not in tiers:
            continue
        if not english:
            continue
        if spec.get("anchored"):
            corpus = text.replace("’", "'")
        else:
            corpus = phrase_corpus
        exclude = spec.get("exclude")
        count = _count_matches(spec["pattern"], corpus, exclude)
        if count == 0:
            continue
        snippets = _find_snippets(spec["pattern"], corpus, exclude)
        if "flat" in spec:
            points = spec["flat"]
        elif short_sample:
            points = 0.0
        else:
            rate = count * 1000.0 / prose_chars
            points = spec["weight"] * min(rate, spec["cap"])
        metrics[spec["id"]] = {
            "count": count,
            "points": round(points, 2),
            "snippets": snippets,
        }
        score += points
        if spec["tier"] == "hard":
            hard_violations.append({
                "id": spec["id"],
                "count": count,
                "snippets": snippets,
                "advice": spec.get("advice", "remove this pattern"),
            })

    if "soft" in tiers and english:
        algo_points = {
            "staccato": _staccato_points(sentences),
            "uniformity": _uniformity_points(sentences),
            "aphoristic_closer": _aphoristic_closer_points(phrase_corpus),
            "bold_term_list": _bold_term_list_points(text),
            "exclaim": _exclaim_points(phrase_corpus),
        }
        for metric_id, points in algo_points.items():
            if points > 0:
                metrics[metric_id] = {"count": None,
                                      "points": round(points, 2),
                                      "snippets": []}
                score += points

    return {
        "prose_chars": prose_chars,
        "sentences": len(sentences),
        "short_sample": short_sample,
        "english": english,
        "metrics": metrics,
        "score": round(min(score, 100.0), 1),
        "hard_violations": hard_violations,
        "verdict": "block" if hard_violations else "pass",
    }


def lint_hard(text):
    """Blocking-linter entry: hard tier only."""
    return evaluate(text, tiers=("hard",))


# ---------------------------------------------------------------------------
# Comment extraction for the file linter
# ---------------------------------------------------------------------------
# Only file types with well-understood comment syntax; anything else
# is skipped so the extractor can never misfire on unknown formats.

HASH_COMMENT_EXTS = (".py", ".rb", ".sh", ".bash", ".zsh", ".pl")
SLASH_COMMENT_EXTS = (".js", ".jsx", ".ts", ".tsx", ".swift", ".kt",
                      ".java", ".go", ".c", ".h", ".cpp", ".hpp",
                      ".rs", ".scala", ".cs")
PROSE_EXTS = (".md", ".rst", ".txt")

_DOCSTRING_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.S)
_HASH_LINE_RE = re.compile(r"(?m)#(?!!)([^\n]*)$")
_BLOCK_COMMENT_RE = re.compile(r"/\*(.*?)\*/", re.S)
_SLASH_LINE_RE = re.compile(r"(?m)(?<!:)//([^\n]*)$")
_STRING_RE = re.compile(
    r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\''
    r"|`(?:[^`\\]|\\.)*`")


def extract_comments(content, ext):
    """Return the comment text spans of a code file, or [] for file
    types the extractor does not understand."""
    if ext in HASH_COMMENT_EXTS:
        docstrings = []
        if ext == ".py":
            docstrings = [g for m in _DOCSTRING_RE.finditer(content)
                          for g in m.groups() if g]
        stripped = _STRING_RE.sub('""', content)
        return docstrings + [m.group(1) for m in
                             _HASH_LINE_RE.finditer(stripped)]
    if ext in SLASH_COMMENT_EXTS:
        stripped = _STRING_RE.sub('""', content)
        out = [m.group(1) for m in _BLOCK_COMMENT_RE.finditer(stripped)]
        out += [m.group(1) for m in _SLASH_LINE_RE.finditer(stripped)]
        return out
    return []


if __name__ == "__main__":
    import sys

    input_text = sys.stdin.read()
    print(json.dumps(evaluate(input_text), indent=2))
