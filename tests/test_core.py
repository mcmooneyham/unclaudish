"""Unit tests for claudish_core and lint_stop.

Detection fixtures are built at runtime from unicode escapes so no
source file contains a literal em dash. Run:
    python3 tests/test_core.py -v
"""

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import claudish_core as cc  # noqa: E402

EM = "\u2014"
EN = "\u2013"
CURLY = "\u2019"
LINT_STOP = os.path.join(REPO_ROOT, "scripts", "lint_stop.py")


def hard_ids(text):
    return sorted(v["id"] for v in cc.lint_hard(text)["hard_violations"])


PAD = (" The service retries twice with backoff, then falls back to the"
       " cache. All three integration tests cover this path and pass"
       " on CI. See the runbook for the rollback steps and the alert"
       " thresholds that page the on-call engineer.")


class HardTierDetection(unittest.TestCase):
    def test_em_dash_blocks(self):
        self.assertIn("em_dash", hard_ids("The fix" + EM + "as shipped."))

    def test_em_dash_variants_block(self):
        self.assertIn("em_dash", hard_ids("a ⸺ b"))
        self.assertIn("em_dash", hard_ids("a ⸻ b"))

    def test_spaced_en_dash_clause_blocks(self):
        self.assertIn("em_dash", hard_ids("The fix " + EN + " as shipped."))

    def test_sycophantic_opener_blocks(self):
        for opener in ["You're absolutely right!",
                       "You" + CURLY + "re totally correct.",
                       "Great question!",
                       "Great catch.",
                       "Excellent point."]:
            self.assertTrue(
                cc.lint_hard(opener + PAD)["hard_violations"],
                "opener not caught: %r" % opener,
            )

    def test_sycophancy_mid_message_blocks(self):
        text = "The cache is stale. You're absolutely right about the TTL."
        self.assertIn("syco_anywhere", hard_ids(text))

    def test_heres_the_thing_blocks(self):
        text = "Here" + CURLY + "s the thing: the index is unused."
        self.assertIn("heres_the_thing", hard_ids(text))

    def test_worth_noting_blocks(self):
        self.assertIn("worth_noting",
                      hard_ids("It's worth noting that tests fail."))
        self.assertIn("worth_noting",
                      hard_ids("It is important to note the limit."))

    def test_crucially_blocks(self):
        self.assertIn("crucially",
                      hard_ids("The job ran. Crucially, it ran twice."))

    def test_delve_blocks(self):
        self.assertIn("delve", hard_ids("Let us delve into the config."))
        self.assertIn("delve", hard_ids("Delving deeper, the bug is real."))

    def test_short_message_with_em_dash_still_blocks(self):
        result = cc.lint_hard("OK" + EM + "done.")
        self.assertEqual(result["verdict"], "block")


class FalsePositiveTraps(unittest.TestCase):
    def assert_clean(self, text, msg=None):
        result = cc.lint_hard(text)
        self.assertEqual(
            result["verdict"], "pass",
            msg or "false positive: %s" % result["hard_violations"],
        )

    def test_fenced_code_ignored(self):
        text = ("Run the script below.\n```python\n"
                "s = 'a" + EM + "b'  # delve crucially\n```\nDone.")
        self.assert_clean(text)

    def test_tilde_fence_ignored(self):
        text = "See:\n~~~\nx " + EM + " y\n~~~\nDone."
        self.assert_clean(text)

    def test_unclosed_fence_swallows_remainder(self):
        text = "Output:\n```\ntruncated " + EM + " stream delve"
        self.assert_clean(text)

    def test_inline_code_ignored(self):
        self.assert_clean("Use `a" + EM + "b` as the key.")

    def test_double_backtick_inline_ignored(self):
        self.assert_clean("Use ``a ` b" + EM + "`` here.")

    def test_cli_flags_not_dashes(self):
        self.assert_clean("Run with --verbose and --dry-run flags.")

    def test_table_and_hr_not_dashes(self):
        self.assert_clean("| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n")

    def test_en_dash_range_allowed(self):
        self.assert_clean("See pages 10" + EN + "12 and 2019" + EN + "2021.")

    def test_blockquote_ignored(self):
        self.assert_clean("> You're absolutely right" + EM + "a footgun.\n"
                          "The quote above is from the issue.")

    def test_microsoft_delve_excluded(self):
        self.assert_clean("The file lives in Microsoft Delve.")

    def test_engineering_gated_landed_not_hard(self):
        self.assert_clean("The merge is gated on CI. "
                          "The commit landed on main yesterday.")

    def test_soft_jargon_never_blocks(self):
        self.assert_clean("The blast radius of the outage was one shard, "
                          "a known footgun in the SRE runbook.")

    def test_concession_leads_with_the_fact(self):
        # The bare agreement opener blocks like the intensified one:
        # a concession states the fact first.
        self.assertIn("syco_opener",
                      hard_ids("You're right, the limit is 100, not 1000."))
        self.assert_clean("The limit is 100, not 1000. You had that right.")

    def test_right_that_is_an_answer_not_an_opener(self):
        self.assert_clean(
            "You're right that WAL isolates readers, so keep SQLite.")

    def test_quoted_mention_not_flagged(self):
        self.assert_clean(
            'The linter bans "Here\'s the thing" and phrases like '
            '"You\'re absolutely right" when they open a message.'
        )
        self.assert_clean('The doc says "a' + EM + 'b" verbatim.')

    def test_unquoted_use_still_blocks(self):
        text = ('We discussed "delve" earlier. Here' + CURLY +
                "s the thing: the quota is gone.")
        self.assertIn("heres_the_thing", hard_ids(text))

    def test_urls_and_slugs_ignored(self):
        self.assert_clean(
            "See https://example.com/heres-the-thing and the file "
            "[notes](./not-just-a-blog.md)."
        )

    # Regression tests from the adversarial review (confirmed findings)

    def test_russian_copula_dash_not_blocked(self):
        # FP-1: the em dash is correct Russian typography
        self.assert_clean(
            ("Москва " + EM +
             " столица. ") * 12
        )

    def test_line_initial_dash_not_blocked(self):
        # FP-1: dialogue and attribution dashes open the line
        self.assert_clean(EM + " Anonymous\n" + EM + " Hola, dijo Maria.")

    def test_spaced_en_dash_between_digits_ok(self):
        # FP-2: scores, hours, date ranges
        self.assert_clean("The final score was 3 " + EN + " 1 and the "
                          "shop is open 9 " + EN + " 5 on weekdays.")

    def test_go_debugger_delve_not_blocked(self):
        # FP-3
        self.assert_clean(
            "To step through the Go service, install Delve first, then "
            "run dlv debug. Delve supports conditional breakpoints."
        )

    def test_surname_delves_not_blocked(self):
        self.assert_clean("Peter Delves co-wrote the immunology text.")

    def test_delve_into_still_blocks(self):
        self.assertIn("delve", hard_ids("Let us delve into the config."))
        self.assertIn("delve", hard_ids("Delving deeper, the bug is real."))

    def test_single_quoted_mention_not_blocked(self):
        # FP-4: mentions wrapped in straight single quotes
        self.assert_clean(
            "This linter blocks 'here's the thing' and 'it's worth "
            "noting' wherever they appear, plus the word 'delve'."
        )

    def test_long_double_quote_not_blocked(self):
        # STYLE-01/FP-4: verbatim quotes over 80 chars
        quoted = ("You're absolutely right to be worried about the "
                  "memory usage in the export worker, and the fix you "
                  "proposed for the queue is the one we shipped.")
        self.assert_clean('The reviewer wrote: "%s" and I agree with '
                          "the substance of it." % quoted)

    def test_conditional_sycophancy_not_blocked(self):
        # FP-5
        self.assert_clean(
            "Even if you're absolutely right about the schema drift, "
            "the migration still fails on the older tenants."
        )

    def test_spelled_out_sycophancy_blocks(self):
        # syco-spelled-out
        self.assertIn("syco_anywhere",
                      hard_ids("You are absolutely right about the TTL."))

    def test_noun_phrase_opener_not_blocked(self):
        # FP-6
        self.assert_clean(
            "Great question detection is the first feature this linter "
            "ships, and it needs holdout data."
        )
        self.assertTrue(cc.lint_hard("Great question! The fix is easy."
                                     + PAD)["hard_violations"])

    def test_indented_code_with_dash_not_blocked(self):
        # FP-4: indented code blocks
        self.assert_clean("Example:\n\n    label = 'a" + EM + "b'\n"
                          "    return label\n\nThat is the whole fix.")

    def test_diff_lines_not_blocked(self):
        self.assert_clean("The patch:\n\n"
                          "-old = 'a" + EM + "b delve'\n"
                          "+new = 'plain'\n\nApplied cleanly.")

    def test_link_title_with_claudish_not_blocked(self):
        self.assert_clean(
            "See [Delving into ChatGPT usage" + EM +
            "a corpus study](https://example.com/paper) for numbers."
        )

    def test_abbreviations_do_not_break_sentences(self):
        _, sentence_corpus, _ = cc.preprocess(
            "Dr. Smith shipped v2.1.3 yesterday. It works, e.g. on macOS."
        )
        self.assertEqual(len(cc.split_sentences(sentence_corpus)), 2)

    def test_non_english_text_never_blocks(self):
        # FP-1: all hard metrics, em dash included, skip non-English
        # prose, where the em dash can be correct typography.
        russian = ("Это важно. " * 30)
        self.assertEqual(cc.lint_hard(russian)["verdict"], "pass")
        self.assertEqual(
            cc.lint_hard(russian + " a" + EM + "b ")["verdict"], "pass"
        )


class SoftTierScoring(unittest.TestCase):
    def test_claudish_scores_higher_than_plain(self):
        claudish = (
            "It's not just a bug, but a symptom. The real problem isn't "
            "the cache. Not the config. Not the deploy. The model. "
            "Importantly, the fix is load-bearing and battle-tested. "
            "That's the whole story." + PAD
        )
        plain = (
            "The bug is in the cache key builder. The fix renames the "
            "tenant field and adds a regression test." + PAD
        )
        self.assertGreater(cc.evaluate(claudish)["score"],
                           cc.evaluate(plain)["score"])

    def test_bold_lead_sentence_list_detected(self):
        text = ("- **Speed is a non-issue.** The queue is small.\n"
                "- **Cost is a non-issue.** One system, not two.\n"
                "- **Risk is a non-issue.** Rollback is a flag.\n" + PAD)
        self.assertIn("bold_term_list", cc.evaluate(text)["metrics"])

    def test_mandated_colon_list_is_not_scored(self):
        # Both styles ask for '**Term:** description', so scoring it
        # penalised replies for following the guide.
        text = ("- **Speed:** fast.\n- **Cost:** low.\n"
                "- **Risk:** none.\n" + PAD)
        self.assertNotIn("bold_term_list", cc.evaluate(text)["metrics"])

    def test_appositive_contrast_detected(self):
        text = ("Operational load goes down, not up. The vacuum work "
                "is a tuning task, not a design risk." + PAD)
        self.assertIn("contrast_appositive",
                      cc.evaluate(text)["metrics"])

    def test_staged_emphasis_detected(self):
        text = ("The strongest argument here: transactional enqueue. "
                "The one thing to watch is autovacuum." + PAD)
        self.assertIn("staged_emphasis", cc.evaluate(text)["metrics"])

    def test_full_bold_lead_bullet_detected(self):
        text = ("- **Volume is a non-issue.** It is tiny.\n"
                "- **Durability is default.** WAL covers it.\n"
                "- **Ops go down.** One fewer system.\n" + PAD)
        self.assertIn("bold_term_list", cc.evaluate(text)["metrics"])

    def test_soft_hits_never_produce_block_verdict(self):
        text = "Not just fast but correct. Importantly, it works." + PAD
        self.assertEqual(cc.lint_hard(text)["verdict"], "pass")


class ApprovedTermExpansion(unittest.TestCase):
    """Field-guide Scores terms (approved 2026-08-25)."""

    def detected(self, text, metric):
        return metric in cc.evaluate(text + PAD)["metrics"]

    def test_authenticity_frames_score(self):
        for text in ["This is a real issue, not a style nit.",
                     "One honest caveat from the probe.",
                     "The actual fix is one line.",
                     "That is genuinely hard to test."]:
            self.assertTrue(self.detected(text, "authenticity_adj"), text)

    def test_craft_praise_scores(self):
        self.assertTrue(self.detected(
            "This is the clean fix: move validation into the setter.",
            "craft_adj"))
        self.assertTrue(self.detected(
            "A surgical change with proper indexes.", "craft_adj"))

    def test_verdict_verbs_score(self):
        for text in ["The argument holds up under review.",
                     "That buys you nothing at this volume.",
                     "The tap wins outright.",
                     "Which is exactly why the importer matches by title."]:
            self.assertTrue(self.detected(text, "verdict_verbs"), text)

    def test_quiet_verbs_score(self):
        self.assertTrue(self.detected(
            "The parser silently drops long titles.", "quiet_verbs"))

    def test_wiring_scores(self):
        self.assertTrue(self.detected(
            "Now the route wiring for the fifth tab.", "wiring_metaphor"))

    def test_legit_uses_not_scored(self):
        for text, metric in [
            ("The test compares expected and actual output.",
             "authenticity_adj"),
            ("We tested against real data instead of mocks.",
             "authenticity_adj"),
            ("The branch merges cleanly and the clean build passed.",
             "craft_adj"),
            ("A proper subset of the config keys is required.",
             "craft_adj"),
            ("The write fails silently when the disk is full.",
             "quiet_verbs"),
        ]:
            self.assertFalse(self.detected(text, metric), text)

    def test_new_terms_never_block(self):
        text = ("One honest caveat: the clean fix buys you nothing, "
                "which is exactly why the wiring silently drops it.")
        self.assertEqual(cc.lint_hard(text + PAD)["verdict"], "pass")


class OfferClosers(unittest.TestCase):
    def test_question_offer_not_aphoristic(self):
        text = ("Move it to Postgres. It is durable by default and one "
                "less system to run." + PAD + "\n\nWant the schema?")
        self.assertNotIn("aphoristic_closer",
                         cc.evaluate(text)["metrics"])

    def test_single_sentence_reply_not_a_closer(self):
        text = "The tests pass and the rollback is documented."
        self.assertNotIn("aphoristic_closer",
                         cc.evaluate(text)["metrics"])

    def test_statement_closer_still_scored(self):
        text = PAD + "\n\nThat's the whole story."
        self.assertIn("aphoristic_closer", cc.evaluate(text)["metrics"])


class ResidueMetrics(unittest.TestCase):
    """Process-residue detection (scored tier, never blocks)."""

    RESIDUE = ("residue_archaeology", "residue_verification",
               "residue_machinery")

    def found(self, text):
        metrics = cc.evaluate(text + PAD)["metrics"]
        return [m for m in self.RESIDUE if m in metrics]

    def test_positives_detected(self):
        for text in [
            "An adversarial review pass: 44 findings hunted, 12 "
            "confirmed, all fixed with regression tests.",
            "Excluded: 25 runs contaminated by a since-fixed bug.",
            "The judge panel scored all three drafts.",
            "Everything is verified end to end and all green.",
            "All 12 confirmed findings were fixed.",
        ]:
            self.assertTrue(self.found(text), text)

    def test_negatives_clean(self):
        for text in [
            "0% of the 45 runs contained a blockable pattern.",
            "Changelog: the parser no longer drops trailing newlines.",
            "Run python3 tests/test_core.py before sending a PR.",
            "The green deployment path skips the canary.",
            "The review found the restaurant charming.",
            "Retries are attempted 3 times with backoff.",
        ]:
            self.assertFalse(self.found(text), text)

    def test_residue_never_blocks(self):
        text = ("The adversarial review confirmed 12 findings, all "
                "fixed and verified end to end." + PAD)
        self.assertEqual(cc.lint_hard(text)["verdict"], "pass")


class CommentExtraction(unittest.TestCase):
    def test_python_comment_and_docstring(self):
        code = ('def f():\n    """Crucially, this delves into it."""\n'
                "    x = 1  # the fix" + EM + "as shipped\n")
        joined = "\n".join(cc.extract_comments(code, ".py"))
        self.assertIn("Crucially", joined)
        self.assertIn(EM, joined)

    def test_string_literals_invisible(self):
        code = 'banner = "# not a comment ' + EM + '"\n'
        self.assertFalse(
            any(EM in c for c in cc.extract_comments(code, ".py")))
        js = 'const u = "https://example.com/x"; // ok\n'
        joined = "\n".join(cc.extract_comments(js, ".js"))
        self.assertNotIn("example.com", joined)

    def test_shebang_skipped(self):
        comments = cc.extract_comments(
            "#!/usr/bin/env python3\nx = 1\n", ".py")
        self.assertFalse(any("usr/bin" in c for c in comments))

    def test_slash_languages(self):
        code = "/* You're absolutely right */\nlet a; // b" + EM + "c\n"
        for ext in (".js", ".swift", ".go", ".rs"):
            joined = "\n".join(cc.extract_comments(code, ext))
            self.assertIn("absolutely right", joined)
            self.assertIn(EM, joined)

    def test_unknown_types_skipped(self):
        for ext in (".yaml", ".json", ".html", ".css", ""):
            self.assertEqual(
                cc.extract_comments("# x " + EM, ext), [])


class LintFileProcess(unittest.TestCase):
    """Contract tests for the PreToolUse file linter."""

    LINT_FILE = os.path.join(REPO_ROOT, "scripts", "lint_file.py")

    def setUp(self):
        shutil.rmtree(os.path.join(tempfile.gettempdir(),
                                   "unclaudish-state"),
                      ignore_errors=True)

    def run_hook(self, payload, mode=None):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        self.home = getattr(self, "home", None) or \
            tempfile.mkdtemp(prefix="lintfile-home-")
        env["HOME"] = self.home
        claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        if mode is not None:
            with open(os.path.join(claude_dir,
                                   "unclaudish-mode"), "w") as f:
                f.write(mode)
        return subprocess.run(
            [sys.executable, self.LINT_FILE],
            input=json.dumps(payload).encode() if isinstance(
                payload, dict) else payload,
            capture_output=True, env=env, timeout=10)

    def hook_payload(self, path, content, prompt="p1"):
        return {"hook_event_name": "PreToolUse", "tool_name": "Write",
                "prompt_id": prompt,
                "tool_input": {"file_path": path, "content": content}}

    def test_denies_claudish_comment(self):
        proc = self.run_hook(self.hook_payload(
            "/tmp/x.py", "x = 1  # the fix" + EM + "as shipped\n"))
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allows_clean_code_with_dash_in_string(self):
        proc = self.run_hook(self.hook_payload(
            "/tmp/x.py", 'sep = "' + EM + '"  # separator constant\n'))
        self.assertEqual(proc.stdout.strip(), b"")

    def test_denies_claudish_markdown(self):
        proc = self.run_hook(self.hook_payload(
            "/tmp/README.md", "You're absolutely right" + EM + "done."))
        self.assertIn(b"deny", proc.stdout)

    def test_allows_unknown_filetype(self):
        proc = self.run_hook(self.hook_payload(
            "/tmp/data.yaml", "note: a" + EM + "b\n"))
        self.assertEqual(proc.stdout.strip(), b"")

    def test_deny_cap_prevents_wedging(self):
        payload = self.hook_payload(
            "/tmp/x.py", "# a" + EM + "b\n", "p9")
        first = self.run_hook(payload)
        second = self.run_hook(payload)
        third = self.run_hook(payload)
        self.assertIn(b"deny", first.stdout)
        self.assertIn(b"deny", second.stdout)
        self.assertEqual(third.stdout.strip(), b"")

    def test_edit_new_string_checked(self):
        payload = {"hook_event_name": "PreToolUse",
                   "tool_name": "Edit", "prompt_id": "p2",
                   "tool_input": {"file_path": "/tmp/x.js",
                                  "old_string": "let a;",
                                  "new_string": "let a; // b" + EM + "c"}}
        proc = self.run_hook(payload)
        self.assertIn(b"deny", proc.stdout)

    def test_moved_existing_text_not_denied(self):
        import tempfile as tf
        with tf.NamedTemporaryFile("w", suffix=".py", delete=False,
                                   encoding="utf-8") as f:
            f.write("# It is important to note that Karr defines "
                    "all sums\nx = 1\n")
            path = f.name
        try:
            payload = self.hook_payload(
                path, "y = 2\n# It is important to note that Karr "
                "defines all sums\n")
            proc = self.run_hook(payload)
            self.assertEqual(proc.stdout.strip(), b"",
                             "moved text was denied")
            payload2 = self.hook_payload(
                path, "# It is important to note the cache is new\n")
            proc2 = self.run_hook(payload2)
            self.assertIn(b"deny", proc2.stdout)
        finally:
            os.unlink(path)

    def test_mode_off_disables_file_linter(self):
        proc = self.run_hook(self.hook_payload(
            "/tmp/x.py", "x = 1  # a" + EM + "b\n"), mode="off")
        self.assertEqual(proc.stdout.strip(), b"")

    def test_fail_open_on_garbage(self):
        for payload in (b"", b"not json", b"[]"):
            proc = self.run_hook(payload)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout.strip(), b"")


class EditsSeeTheWholeFile(unittest.TestCase):
    """An edit sends a fragment; the linter parses the finished file.

    Without this, a docstring edited one line at a time is invisible,
    because a fragment cannot be parsed and no string in it can be
    told apart from a data literal.
    """

    LINT_FILE = os.path.join(REPO_ROOT, "scripts", "lint_file.py")
    SOURCE = ('def revoke(token):\n'
              '    """Revoke the refresh token."""\n'
              '    token.revoked = True\n'
              '\n'
              'PENDING = """\n'
              'SELECT a - b FROM t\n'
              '"""\n')

    def setUp(self):
        shutil.rmtree(os.path.join(tempfile.gettempdir(),
                                   "unclaudish-state"), ignore_errors=True)
        self.home = tempfile.mkdtemp(prefix="edit-home-")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.work = tempfile.mkdtemp(prefix="edit-work-")
        self.path = os.path.join(self.work, "auth.py")
        with open(self.path, "w") as f:
            f.write(self.SOURCE)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def edit(self, old_string, new_string, path=None, prompt="p",
             replace_all=False):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                   "prompt_id": prompt,
                   "tool_input": {"file_path": path or self.path,
                                  "old_string": old_string,
                                  "new_string": new_string,
                                  "replace_all": replace_all}}
        out = subprocess.run([sys.executable, self.LINT_FILE],
                             input=json.dumps(payload).encode(),
                             capture_output=True, env=env,
                             timeout=10).stdout
        return b"deny" in out

    def test_claudish_edited_into_a_docstring_is_denied(self):
        self.assertTrue(self.edit(
            '    """Revoke the refresh token."""',
            '    """It\'s worth noting that this commits."""'))

    def test_clean_docstring_edit_passes(self):
        self.assertFalse(self.edit(
            '    """Revoke the refresh token."""',
            '    """Revoke the token inside the caller transaction."""'))

    def test_edit_inside_a_data_literal_passes(self):
        self.assertFalse(self.edit("SELECT a - b FROM t",
                                   "SELECT a - b, c - d FROM t"))

    def test_untouched_claudish_elsewhere_is_not_charged_to_this_edit(self):
        with open(self.path, "w") as f:
            f.write('def f():\n'
                    '    """It\'s worth noting that this commits."""\n'
                    '    return 1\n')
        self.assertFalse(self.edit("    return 1", "    return 2"))

    def test_comment_edits_are_still_checked(self):
        self.assertTrue(self.edit("    token.revoked = True",
                                  "    # Here's the thing: it commits.\n"
                                  "    token.revoked = True"))

    def test_internal_marker_edits_are_exempt(self):
        self.assertFalse(self.edit(
            "    token.revoked = True",
            "    # TODO: here's the thing, add retries\n"
            "    token.revoked = True"))

    def test_missing_file_falls_back_to_the_fragment(self):
        missing = os.path.join(self.work, "nope.py")
        self.assertTrue(self.edit("x", "# Here's the thing: no file.",
                                  path=missing))

    def test_old_string_not_in_the_file_falls_back(self):
        self.assertTrue(self.edit("nothing like this exists",
                                  "# Here's the thing: no match."))

    def test_replace_all_is_honoured(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import lint_file
        existing = "a = 1\nb = 1\n"
        once = lint_file.projected_file(
            existing, {"old_string": "1", "new_string": "2"})
        every = lint_file.projected_file(
            existing, {"old_string": "1", "new_string": "2",
                       "replace_all": True})
        self.assertEqual(once, "a = 2\nb = 1\n")
        self.assertEqual(every, "a = 2\nb = 2\n")

    def test_write_of_a_whole_file_still_works(self):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                   "prompt_id": "w",
                   "tool_input": {"file_path": self.path,
                                  "content": 'def f():\n'
                                             '    """It\'s worth noting'
                                             ' that this commits."""\n'}}
        out = subprocess.run([sys.executable, self.LINT_FILE],
                             input=json.dumps(payload).encode(),
                             capture_output=True, env=env,
                             timeout=10).stdout
        self.assertIn(b"deny", out)


class RemindModes(unittest.TestCase):
    """The turn hook is what makes a mode change work without /clear.

    First turn under a mode carries the whole style file; later turns
    carry the short reminder.
    """

    REMIND = os.path.join(REPO_ROOT, "scripts", "remind.py")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="remind-home-")
        self.state = tempfile.mkdtemp(prefix="remind-state-")
        os.makedirs(os.path.join(self.home, ".claude"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def run_remind(self, mode, session="s1"):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        env["TMPDIR"] = self.state
        mode_path = os.path.join(self.home, ".claude", "unclaudish-mode")
        if mode is None:
            if os.path.exists(mode_path):
                os.unlink(mode_path)
        else:
            with open(mode_path, "w") as f:
                f.write(mode + "\n")
        payload = json.dumps({"hook_event_name": "UserPromptSubmit",
                              "session_id": session,
                              "prompt": "hi"}).encode()
        out = subprocess.run([sys.executable, self.REMIND],
                             input=payload, capture_output=True,
                             env=env, timeout=10).stdout
        if not out:
            return ""
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_default_mode_injects_the_plain_style(self):
        text = self.run_remind(None)
        self.assertIn("The deletion test", text)

    def test_on_mode_injects_the_plain_style(self):
        text = self.run_remind("on")
        self.assertIn("The deletion test", text)

    def test_legacy_flag_value_treated_as_on(self):
        text = self.run_remind("unclaudish")
        self.assertIn("The deletion test", text)

    def test_max_mode_injects_the_max_style(self):
        text = self.run_remind("max")
        self.assertIn("sharp colleague", text)

    def test_later_turns_use_the_short_reminder(self):
        first = self.run_remind("max")
        second = self.run_remind("max")
        self.assertIn("sharp colleague", second)
        self.assertLess(len(second), len(first))
        self.assertIn("Under 60 words", second)

    def test_a_mode_change_reinjects_the_full_style(self):
        self.run_remind("max")
        self.run_remind("max")
        switched = self.run_remind("on")
        self.assertIn("The deletion test", switched)

    def test_each_session_gets_the_full_style_once(self):
        self.run_remind("max", session="s1")
        other = self.run_remind("max", session="s2")
        self.assertIn("sharp colleague", other)
        self.assertIn("complete rules", other)

    def test_off_mode_countermands_style(self):
        text = self.run_remind("off")
        self.assertIn("disregard the unclaudish output style", text)
        self.assertNotIn("deletion test", text)

    def test_kill_switch_silences_the_hook(self):
        open(os.path.join(self.home, ".claude",
                          "unclaudish-off"), "w").close()
        self.assertEqual(self.run_remind("max"), "")

    def test_frontmatter_is_stripped_from_the_injection(self):
        text = self.run_remind("on")
        self.assertNotIn("keep-coding-instructions", text)
        self.assertNotIn("name: unclaudish", text)

    def test_first_turn_also_writes_the_style_setting(self):
        # Installing mid-session plus /reload-plugins skips
        # SessionStart, so the first turn must still sync settings.
        settings = os.path.join(self.home, ".claude", "settings.json")
        with open(settings, "w") as f:
            json.dump({"model": "opus"}, f)
        self.run_remind("max")
        with open(settings) as f:
            self.assertEqual(json.load(f)["outputStyle"],
                             "unclaudish:unclaudish-max")

    def test_malformed_stdin_still_injects(self):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        env["TMPDIR"] = self.state
        proc = subprocess.run([sys.executable, self.REMIND],
                              input=b"not json", capture_output=True,
                              env=env, timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"unclaudish", proc.stdout)


class SubagentInheritance(unittest.TestCase):
    """Subagents get the style through SubagentStart, not the turn hook."""

    SUB = os.path.join(REPO_ROOT, "scripts", "subagent_style.py")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sub-home-")
        self.claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(self.claude_dir)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def write_flag(self, name, value):
        with open(os.path.join(self.claude_dir, name), "w") as f:
            f.write(value + "\n")

    def run_sub(self, *args, env_extra=None):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        if env_extra:
            env.update(env_extra)
        payload = json.dumps({"hook_event_name": "SubagentStart",
                              "session_id": "s1"}).encode()
        return subprocess.run([sys.executable, self.SUB] + list(args),
                              input=payload, capture_output=True,
                              env=env, timeout=10).stdout

    def context_for(self, *args, **kwargs):
        out = self.run_sub(*args, **kwargs)
        if not out:
            return ""
        parsed = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(parsed["hookEventName"], "SubagentStart")
        return parsed["additionalContext"]

    def test_inherits_the_plain_style_by_default(self):
        text = self.context_for("inject")
        self.assertIn("The deletion test", text)

    def test_inherits_the_max_style_in_max_mode(self):
        self.write_flag("unclaudish-mode", "max")
        text = self.context_for("inject")
        self.assertIn("sharp colleague", text)

    def test_structured_returns_are_protected(self):
        text = self.context_for("inject")
        self.assertIn("specific return format", text)

    def test_setting_off_silences_the_hook(self):
        self.write_flag("unclaudish-subagents", "off")
        self.assertEqual(self.context_for("inject"), "")

    def test_no_is_accepted_as_off(self):
        self.write_flag("unclaudish-subagents", "no")
        self.assertEqual(self.context_for("inject"), "")

    def test_mirror_follows_the_session_mode(self):
        self.write_flag("unclaudish-subagents", "mirror")
        self.write_flag("unclaudish-mode", "max")
        self.assertIn("sharp colleague", self.context_for("inject"))
        self.write_flag("unclaudish-mode", "on")
        self.assertIn("The deletion test", self.context_for("inject"))

    def test_mirror_is_the_default_with_no_flag_file(self):
        self.write_flag("unclaudish-mode", "max")
        self.assertIn("sharp colleague", self.context_for("inject"))

    def test_on_pins_the_plain_style_in_a_max_session(self):
        self.write_flag("unclaudish-subagents", "on")
        self.write_flag("unclaudish-mode", "max")
        text = self.context_for("inject")
        self.assertIn("The deletion test", text)
        self.assertNotIn("sharp colleague", text)

    def test_max_pins_the_max_style_in_a_plain_session(self):
        self.write_flag("unclaudish-subagents", "max")
        self.write_flag("unclaudish-mode", "on")
        text = self.context_for("inject")
        self.assertIn("sharp colleague", text)
        self.assertNotIn("The deletion test", text)

    def test_mode_off_beats_a_pinned_setting(self):
        self.write_flag("unclaudish-subagents", "max")
        self.write_flag("unclaudish-mode", "off")
        self.assertEqual(self.context_for("inject"), "")

    def test_setting_names_the_style_without_claiming_the_session(self):
        # A pinned setting can differ from the session, so the note
        # must not tell the agent what the session is using.
        self.write_flag("unclaudish-subagents", "max")
        self.write_flag("unclaudish-mode", "on")
        opening = self.context_for("inject").splitlines()[0]
        self.assertNotIn("session", opening)
        self.assertIn("unclaudish-max", opening)

    def test_mode_off_silences_the_hook(self):
        self.write_flag("unclaudish-mode", "off")
        self.assertEqual(self.context_for("inject"), "")

    def test_kill_switch_silences_the_hook(self):
        open(os.path.join(self.claude_dir, "unclaudish-off"), "w").close()
        self.assertEqual(self.context_for("inject"), "")

    def test_env_disable_silences_the_hook(self):
        self.assertEqual(
            self.context_for("inject",
                             env_extra={"UNCLAUDISH_DISABLE": "1"}), "")

    def test_set_writes_each_setting(self):
        flag = os.path.join(self.claude_dir, "unclaudish-subagents")
        for value, expected in (("off", "off"), ("max", "max"),
                                ("on", "on"), ("mirror", "mirror"),
                                ("yes", "mirror"), ("no", "off")):
            self.run_sub("set", value)
            with open(flag) as f:
                self.assertEqual(f.read().strip(), expected, value)

    def test_status_resolves_what_mirror_means_right_now(self):
        self.write_flag("unclaudish-subagents", "mirror")
        self.write_flag("unclaudish-mode", "max")
        self.assertIn(b"currently max", self.run_sub("status"))

    def test_bad_argument_is_rejected_without_writing(self):
        self.run_sub("set", "maybe")
        self.assertFalse(os.path.exists(
            os.path.join(self.claude_dir, "unclaudish-subagents")))

    def test_hook_registered_for_subagent_start(self):
        with open(os.path.join(REPO_ROOT, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        command = hooks["SubagentStart"][0]["hooks"][0]["command"]
        self.assertIn("subagent_style.py inject", command)

    def test_injected_text_is_the_session_style_verbatim(self):
        # Parity: agents must get the same rules, not a paraphrase.
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import remind
        text = self.context_for("inject")
        self.assertIn(remind.style_body("on"), text)


class SubagentLinting(unittest.TestCase):
    """SubagentStop mirrors Stop, minus structured return values."""

    LINT = os.path.join(REPO_ROOT, "scripts", "lint_subagent.py")
    BAD = ("It's worth noting that the cache never expires."
           " Here's the thing: nobody owns the alert.")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sublint-home-")
        self.state = tempfile.mkdtemp(prefix="sublint-state-")
        os.makedirs(os.path.join(self.home, ".claude"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def write_flag(self, name, value):
        with open(os.path.join(self.home, ".claude", name), "w") as f:
            f.write(value + "\n")

    def run_hook(self, message, agent_id="a1", stop_hook_active=False,
                 env_extra=None):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        env["TMPDIR"] = self.state
        if env_extra:
            env.update(env_extra)
        payload = json.dumps({
            "hook_event_name": "SubagentStop",
            "agent_id": agent_id,
            "agent_type": "general-purpose",
            "stop_hook_active": stop_hook_active,
            "agent_transcript_path": "",
            "last_assistant_message": message,
        }).encode()
        return subprocess.run([sys.executable, self.LINT], input=payload,
                              capture_output=True, env=env,
                              timeout=10).stdout

    def test_blocks_hard_patterns_in_prose(self):
        out = self.run_hook(self.BAD)
        decision = json.loads(out)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("worth_noting", decision["reason"])
        self.assertIn("heres_the_thing", decision["reason"])

    def test_blocks_an_em_dash(self):
        out = self.run_hook("The deploy is fine" + EM + "the retry is not.")
        self.assertIn("em_dash", json.loads(out)["reason"])

    def test_blocks_only_once_per_agent(self):
        self.assertIn(b"block", self.run_hook(self.BAD))
        self.assertEqual(self.run_hook(self.BAD), b"")

    def test_a_second_agent_is_still_checked(self):
        self.run_hook(self.BAD, agent_id="a1")
        self.assertIn(b"block", self.run_hook(self.BAD, agent_id="a2"))

    def test_stop_hook_active_prevents_a_loop(self):
        self.assertEqual(
            self.run_hook(self.BAD, stop_hook_active=True), b"")

    def test_clean_prose_passes(self):
        self.assertEqual(
            self.run_hook("The cache never expires and nobody owns"
                          " the alert."), b"")

    def test_json_return_is_never_blocked(self):
        self.assertEqual(
            self.run_hook(json.dumps({"answer": self.BAD})), b"")

    def test_fenced_json_return_is_never_blocked(self):
        self.assertEqual(
            self.run_hook('```json\n{"answer": "%s"}\n```' % self.BAD), b"")

    def test_json_array_return_is_never_blocked(self):
        self.assertEqual(self.run_hook('[{"a": 1}, {"b": 2}]'), b"")

    def test_inheritance_off_disables_linting(self):
        self.write_flag("unclaudish-subagents", "off")
        self.assertEqual(self.run_hook(self.BAD), b"")

    def test_every_active_setting_still_lints(self):
        for value in ("mirror", "on", "max"):
            self.write_flag("unclaudish-subagents", value)
            self.assertIn(b"block",
                          self.run_hook(self.BAD, agent_id="a-" + value),
                          value)

    def test_mode_off_disables_linting(self):
        self.write_flag("unclaudish-mode", "off")
        self.assertEqual(self.run_hook(self.BAD), b"")

    def test_kill_switch_disables_linting(self):
        open(os.path.join(self.home, ".claude",
                          "unclaudish-off"), "w").close()
        self.assertEqual(self.run_hook(self.BAD), b"")

    def test_env_disable_disables_linting(self):
        self.assertEqual(
            self.run_hook(self.BAD,
                          env_extra={"UNCLAUDISH_DISABLE": "1"}), b"")

    def test_malformed_input_fails_open(self):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["TMPDIR"] = self.state
        proc = subprocess.run([sys.executable, self.LINT],
                              input=b"not json", capture_output=True,
                              env=env, timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")

    def test_uses_the_same_engine_as_the_main_linter(self):
        # Parity: identical text, identical verdict and violation ids.
        import lint_stop
        main_reason = lint_stop.build_reason(
            cc.lint_hard(self.BAD)["hard_violations"])
        agent_reason = json.loads(self.run_hook(self.BAD))["reason"]
        for line in main_reason.splitlines():
            if line.startswith("- "):
                self.assertIn(line, agent_reason)

    def test_hook_registered_for_subagent_stop(self):
        with open(os.path.join(REPO_ROOT, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        command = hooks["SubagentStop"][0]["hooks"][0]["command"]
        self.assertIn("lint_subagent.py", command)


class StatsFooter(unittest.TestCase):
    SHOW_STATS = os.path.join(REPO_ROOT, "scripts", "show_stats.py")

    def run_hook(self, payload, flag="on"):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        self.home = getattr(self, "home", None) or \
            tempfile.mkdtemp(prefix="stats-home-")
        env["HOME"] = self.home
        claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        if flag is not None:
            with open(os.path.join(claude_dir,
                                   "unclaudish-stats"), "w") as f:
                f.write(flag)
        return subprocess.run(
            [sys.executable, self.SHOW_STATS],
            input=json.dumps(payload).encode(),
            capture_output=True, env=env, timeout=10)

    def event(self, delta, index, final, msg="m1"):
        return {"hook_event_name": "MessageDisplay",
                "session_id": "s1", "message_id": msg,
                "index": index, "final": final, "delta": delta}

    def test_footer_on_final_covers_all_chunks(self):
        first = self.run_hook(self.event(
            "The fix" + EM + "shipped. ", 0, False))
        self.assertEqual(first.stdout.strip(), b"")
        second = self.run_hook(self.event(
            "Tests pass.", 1, True))
        out = json.loads(second.stdout)
        content = out["hookSpecificOutput"]["displayContent"]
        self.assertTrue(content.startswith("Tests pass."))
        self.assertIn("`unclaudish`", content)
        self.assertIn("1 blockable", content)
        self.assertIn("`detected` ", content)
        self.assertIn("em_dash x1", content)

    def test_clean_footer_hides_the_zero_counts(self):
        footer = self.footer_for("The cache expires after five minutes.",
                                 "zeros1")
        self.assertNotIn("blockable", footer)
        self.assertNotIn("pattern", footer)
        self.assertIn("100% \u00b7 6 words", footer)

    def test_off_means_silent(self):
        proc = self.run_hook(self.event("Hello.", 0, True, "m2"),
                             flag="off")
        self.assertEqual(proc.stdout.strip(), b"")

    def test_fail_open_on_garbage(self):
        env = dict(os.environ)
        proc = subprocess.run([sys.executable, self.SHOW_STATS],
                              input=b"not json",
                              capture_output=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0)

    def footer_for(self, text, msg):
        out = self.run_hook(self.event(text, 0, True, msg))
        return json.loads(out.stdout)["hookSpecificOutput"][
            "displayContent"]

    def test_clean_reply_scores_100(self):
        footer = self.footer_for(
            "The cache expires after five minutes. Tests pass on CI.",
            "clean1")
        self.assertIn("100%", footer)
        self.assertNotIn("`detected`", footer)

    def test_each_blockable_pattern_costs_ten_points(self):
        # Hard violations do not add to the soft score, so one em dash
        # takes exactly 10 points off.
        footer = self.footer_for("The fix" + EM + "shipped clean.",
                                 "dash1")
        self.assertIn("1 blockable", footer)
        self.assertIn("90%", footer)

    def test_soft_patterns_lower_the_score_by_the_formula(self):
        # The footer must agree with the engine: 100 minus 5 per score
        # point, minus 10 per blockable pattern.
        text = ("The rollout was seamless and the pipeline is robust."
                " We leveraged the framework to unlock a paradigm"
                " shift, and the architecture is bulletproof and"
                " production-ready across the board. ") * 4
        result = cc.evaluate(text)
        expected = max(0.0, 100.0 - 5.0 * result["score"]
                       - 10.0 * sum(v["count"]
                                    for v in result["hard_violations"]))
        footer = self.footer_for(text, "soft1")
        self.assertIn("%.0f%%" % expected, footer)
        self.assertLess(expected, 100)

    def test_score_never_goes_below_zero(self):
        awful = ((("You're absolutely right! Here" + CURLY + "s the "
                   "thing: it" + CURLY + "s worth noting the fix"
                   + EM + "shipped. Crucially, we must delve into "
                   "the robust, seamless, production-ready core. ")
                  * 6))
        footer = self.footer_for(awful, "awful1")
        self.assertIn("0%", footer)

    def test_word_count_covers_the_whole_message(self):
        self.run_hook(self.event("one two three ", 0, False, "words1"))
        footer = self.footer_for_final("four five.", 1, "words1")
        self.assertIn("5 words", footer)

    def footer_for_final(self, text, index, msg):
        out = self.run_hook(self.event(text, index, True, msg))
        return json.loads(out.stdout)["hookSpecificOutput"][
            "displayContent"]

    def test_chunks_are_assembled_in_index_order(self):
        # Chunks can be written out of order; the footer must still
        # evaluate the message as it reads.
        self.run_hook(self.event("shipped.", 1, False, "order1"))
        footer = self.footer_for_final("The fix" + EM, 0, "order1")
        self.assertIn("1 blockable", footer)
        self.assertIn("em_dash", footer)

    def test_only_the_final_chunk_carries_the_footer(self):
        first = self.run_hook(self.event("Half a ", 0, False, "part1"))
        self.assertEqual(first.stdout.strip(), b"")

    def test_display_content_keeps_the_original_delta(self):
        footer = self.footer_for("Tests pass.", "keep1")
        self.assertTrue(footer.startswith("Tests pass."))

    def test_blockable_count_reads_as_a_count(self):
        footer = self.footer_for("The fix" + EM + "shipped clean.",
                                 "one1")
        self.assertIn("\u00b7 1 blockable", footer)

    def test_reply_tokens_are_estimated_with_an_up_arrow(self):
        # The assistant record is written after this hook runs, so the
        # reply's own output can only be an estimate here.
        footer = self.footer_for("x" * 400, "est1")
        self.assertIn("tok: ~100\u2191", footer)

    def write_ledger(self, session, entries):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import usage
        os.makedirs(usage.LEDGER_ROOT, exist_ok=True)
        with open(usage.ledger_path(session), "w") as f:
            json.dump(entries, f)
        return usage.ledger_path(session)

    def test_thinking_and_cost_come_from_the_ledger(self):
        session = "ledger-session"
        path = self.write_ledger(session, {
            "p1": {"output_tokens": 900, "thinking_tokens": 3200,
                   "context_tokens": 20000, "cost_usd": 0.0123},
            "p2": {"output_tokens": 600, "thinking_tokens": 100,
                   "context_tokens": 31400, "cost_usd": 1.7677}})
        payload = self.event("Tests pass.", 0, True, "led1")
        payload["session_id"] = session
        footer = json.loads(self.run_hook(payload).stdout)[
            "hookSpecificOutput"]["displayContent"]
        self.assertIn("100 think", footer)  # newest turn's thinking
        self.assertIn("$1.77", footer)      # that turn's cost, not the sum
        self.assertNotIn("$1.78", footer)
        os.remove(path)

    def test_footer_without_a_ledger_shows_only_the_estimate(self):
        payload = self.event("Tests pass.", 0, True, "noledger")
        payload["session_id"] = "session-with-no-ledger"
        footer = json.loads(self.run_hook(payload).stdout)[
            "hookSpecificOutput"]["displayContent"]
        self.assertIn("\u2191", footer)
        self.assertNotIn("think", footer)
        self.assertNotIn("$", footer)

    def test_unpriced_session_shows_tokens_without_a_price(self):
        session = "unpriced-session"
        path = self.write_ledger(session, {
            "p1": {"output_tokens": 10, "thinking_tokens": 5000,
                   "context_tokens": 5000, "cost_usd": None}})
        payload = self.event("Tests pass.", 0, True, "unpriced1")
        payload["session_id"] = session
        footer = json.loads(self.run_hook(payload).stdout)[
            "hookSpecificOutput"]["displayContent"]
        self.assertIn("5.0k think", footer)
        self.assertNotIn("$", footer)
        os.remove(path)

    def test_evaluated_text_is_kept_for_diagnosis(self):
        self.footer_for("The fix" + EM + "shipped.", "diag1")
        found = []
        for root, _, files in os.walk(
                os.path.join(tempfile.gettempdir(), "unclaudish-stats")):
            if "evaluated.txt" in files and root.endswith("diag1"):
                with open(os.path.join(root, "evaluated.txt")) as f:
                    found.append(f.read())
        self.assertTrue(found and EM in found[0])


class ThirteenFixes(unittest.TestCase):
    """The changes pitched from the corpus review, locked in."""

    STYLES = os.path.join(REPO_ROOT, "output-styles")

    def style(self, name):
        with open(os.path.join(self.STYLES, name), encoding="utf-8") as f:
            return f.read()

    def both_styles(self):
        return [self.style("unclaudish.md"), self.style("unclaudish-max.md")]

    # 1. The bare agreement opener.

    def test_bare_agreement_opener_blocks(self):
        for opener in ("You're right, and I was wrong.",
                       "You are correct, the limit is 100.",
                       "You're absolutely right, it retries twice."):
            self.assertIn("syco_opener", hard_ids(opener), opener)

    # 3. A spaced hyphen faking a dash.

    def test_spaced_hyphen_blocks(self):
        self.assertIn("em_dash",
                      hard_ids("Use WAL - readers never block the writer."))

    def test_hyphen_rule_leaves_real_hyphens_alone(self):
        for clean in ("Run with --verbose and --dry-run flags.",
                      "The window is 10 - 20 seconds.",
                      "It is a well-known limit.",
                      "- a bullet line\n- another bullet line"):
            self.assertEqual(cc.lint_hard(clean)["verdict"], "pass", clean)

    # 6. The mandated list format is not scored. (See SoftTierScoring.)

    # 7. A fence tagged as prose stays scored.

    def test_prose_fence_is_scored(self):
        fenced = "```markdown\n# Notes\n\nThe fix" + EM + "shipped.\n```"
        self.assertIn("em_dash", hard_ids(fenced))

    def test_code_fence_is_still_skipped(self):
        fenced = "```python\nx = 1  # a" + EM + "b\n```"
        self.assertEqual(cc.lint_hard(fenced)["verdict"], "pass")

    def test_every_prose_tag_is_recognised(self):
        for tag in cc.PROSE_FENCE_TAGS:
            fenced = "```%s\nThe fix%sshipped.\n```" % (tag, EM)
            self.assertIn("em_dash", hard_ids(fenced), tag)

    # 8. Blast radius in its literal sense.

    def test_literal_blast_radius_passes(self):
        text = ("Blast radius was limited to discounted carts, and no"
                " data was corrupted." + PAD)
        self.assertNotIn("jargon_blast_radius", cc.evaluate(text)["metrics"])

    def test_rhetorical_blast_radius_scores(self):
        text = "The blast radius of that refactor is enormous." + PAD
        self.assertIn("jargon_blast_radius", cc.evaluate(text)["metrics"])

    # 10. Python's parser decides what a docstring is.

    def test_data_constant_is_not_documentation(self):
        source = 'PENDING = """\nSELECT a - b FROM t\n"""\n'
        self.assertEqual(cc.extract_comments(source, ".py"), [])

    def test_real_docstrings_are_still_read(self):
        source = ('"""Module doc."""\n\n\nclass A:\n    """Class doc."""\n'
                  '\n    def f(self):\n        """Method doc."""\n')
        found = cc.extract_comments(source, ".py")
        self.assertEqual(sorted(found),
                         ["Class doc.", "Method doc.", "Module doc."])

    def test_unparseable_fragment_yields_no_docstrings(self):
        fragment = '    """Doc fragment."""\n    return value\n'
        self.assertEqual(cc.extract_comments(fragment, ".py"), [])

    def test_hash_comments_survive_in_a_fragment(self):
        fragment = "    # Here's the thing: it caches.\n    return value\n"
        self.assertTrue(cc.extract_comments(fragment, ".py"))

    # 12. A wall of text.

    def test_long_unbroken_prose_scores(self):
        wall = ("The cache holds product pages for five minutes and the"
                " keys carry tenant and locale. ") * 12
        self.assertIn("wall_of_text", cc.evaluate(wall)["metrics"])

    def test_structure_resets_the_run(self):
        block = ("The cache holds product pages for five minutes and the"
                 " keys carry tenant and locale. ") * 6
        broken = block + "\n\n- Invalidation is event driven.\n\n" + block
        self.assertNotIn("wall_of_text", cc.evaluate(broken)["metrics"])

    def test_short_reply_is_never_a_wall(self):
        self.assertNotIn("wall_of_text",
                         cc.evaluate("The cache expires after five"
                                     " minutes." + PAD)["metrics"])

    def test_threshold_is_the_measured_one(self):
        self.assertEqual(cc.WALL_OF_TEXT_WORDS, 120)

    def test_sentence_rhythm_check_is_gone(self):
        self.assertFalse(hasattr(cc, "_uniformity_points"))
        self.assertNotIn("uniformity",
                         [m["id"] for m in cc.ALGO_METRICS])

    # Style rules: 2, 4, 5, 9, 13.

    def test_styles_ask_for_the_answer_on_its_own_line(self):
        for text in self.both_styles():
            self.assertIn("own line in bold", " ".join(text.split()))

    def test_styles_protect_content_that_cannot_be_deferred(self):
        for text in self.both_styles():
            # The line wraps differently in each file.
            flat = " ".join(text.split())
            self.assertIn("legal or safety condition", flat)
            self.assertIn("number that changes the decision", flat)

    def test_document_budget_names_what_counts(self):
        # An unscoped budget made the model treat critiques and
        # summaries as documents, and max got longer on 8 of 10 demo
        # prompts. The budget now names the deliverables it covers and
        # says what stays a chat answer.
        for text in self.both_styles():
            flat = " ".join(text.split())
            self.assertIn("named deliverable someone else will read", flat)
            self.assertIn("chat answer under the normal cap", flat)
        # No word ceiling: a published number reads as a target to
        # fill, which is how release notes grew toward 450.
        for text in self.both_styles():
            flat = " ".join(text.split())
            self.assertIn("as long as its material and no longer", flat)
            self.assertIn("invent nothing to fill a section", flat)
            self.assertIn("Each fact appears once", flat)
            self.assertNotIn("450 words", flat)
            self.assertNotIn("250 to 500 words", flat)

    def test_styles_tie_the_offer_to_this_reply(self):
        for text in self.both_styles():
            self.assertIn("never out of habit", " ".join(text.split()))

    def test_worked_examples_drop_the_stock_closer(self):
        # The example taught one closing line, and it became a tic.
        for text in self.both_styles():
            head = text.split("## ")[0]
            self.assertNotIn("Want the schema?", head)

    def test_styles_require_content_under_a_heading(self):
        for text in self.both_styles():
            self.assertIn("Never stack a heading on another heading",
                          " ".join(text.split()))

    def test_styles_ask_to_break_a_wall_of_text(self):
        for text in self.both_styles():
            self.assertIn("120 words", text)

    def test_styles_obey_their_own_wall_rule(self):
        for name in ("unclaudish.md", "unclaudish-max.md"):
            self.assertNotIn("wall_of_text",
                             cc.evaluate(self.style(name))["metrics"], name)

    # 11. Internal markers in the file linter.

    def test_internal_markers_are_exempt(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import lint_file
        for marker in ("TODO", "FIXME", "XXX", "HACK", "NOTE"):
            line = " %s: here's the thing, fix retries" % marker
            self.assertTrue(lint_file.INTERNAL_MARKER_RE.match(line), marker)

    def test_ordinary_comments_are_not_exempt(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import lint_file
        self.assertFalse(
            lint_file.INTERNAL_MARKER_RE.match(" Here's the thing: it caches."))


class UsageAccounting(unittest.TestCase):
    """Estimated tokens at display time, real ones from the ledger."""

    LINT_STOP = LINT_STOP

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import usage
        self.usage = usage
        self.tmp = tempfile.mkdtemp(prefix="usage-")
        self.session = "test-session-%d" % id(self)

    def tearDown(self):
        path = self.usage.ledger_path(self.session)
        if os.path.exists(path):
            os.remove(path)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def transcript(self, entries, name="t.jsonl"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        return path

    def assistant(self, out=100, think=0, inp=0, cache=0,
                  model="claude-sonnet-5"):
        return {"type": "assistant", "message": {
            "model": model,
            "usage": {"output_tokens": out, "input_tokens": inp,
                      "cache_read_input_tokens": cache,
                      "output_tokens_details": {"thinking_tokens": think}}}}

    def test_estimate_is_four_characters_per_token(self):
        self.assertEqual(self.usage.estimate_tokens("x" * 400), 100)
        self.assertEqual(self.usage.estimate_tokens(""), 0)
        self.assertEqual(self.usage.estimate_tokens(None), 0)

    def test_cost_uses_the_published_rates(self):
        # sonnet: 1000 in at $2/Mtok, 10000 cache reads at a tenth of
        # that, 2000 out at $10/Mtok.
        cost = self.usage.cost_for("claude-sonnet-5", 1000, 10000, 2000)
        self.assertAlmostEqual(cost, 0.0240, places=6)

    def test_each_model_family_is_priced(self):
        for model, expected in (("claude-fable-5", 50.0),
                                ("claude-opus-5", 25.0),
                                ("claude-sonnet-5", 10.0),
                                ("claude-haiku-4-5", 5.0)):
            cost = self.usage.cost_for(model, 0, 0, 1_000_000)
            self.assertAlmostEqual(cost, expected, places=6, msg=model)

    def test_unknown_model_has_no_price(self):
        self.assertIsNone(self.usage.cost_for("some-model", 1, 1, 1))

    def test_turn_totals_sums_the_current_turn_only(self):
        path = self.transcript([
            self.assistant(out=500),
            {"type": "user", "message": {"content": "next prompt"}},
            self.assistant(out=100, think=20),
            self.assistant(out=50, think=5),
        ])
        totals = self.usage.turn_totals(path)
        self.assertEqual(totals["output_tokens"], 150)
        self.assertEqual(totals["thinking_tokens"], 25)

    def test_turn_totals_is_none_before_the_record_lands(self):
        path = self.transcript([{"type": "attachment"}])
        self.assertIsNone(self.usage.turn_totals(path))

    def test_turn_totals_is_none_for_a_missing_file(self):
        self.assertIsNone(self.usage.turn_totals("/nope/none.jsonl"))

    def test_waiting_returns_as_soon_as_the_record_lands(self):
        path = self.transcript([self.assistant(out=80)])
        start = time.monotonic()
        totals = self.usage.turn_totals_wait(path, timeout=2.0)
        self.assertEqual(totals["output_tokens"], 80)
        self.assertLess(time.monotonic() - start, 0.5)

    def test_waiting_picks_up_a_late_write(self):
        # The record can land a moment after Stop fires.
        import threading
        path = self.transcript([{"type": "attachment"}], "late.jsonl")

        def append_later():
            time.sleep(0.15)
            with open(path, "a") as f:
                f.write(json.dumps(self.assistant(out=64)) + "\n")

        writer = threading.Thread(target=append_later)
        writer.start()
        totals = self.usage.turn_totals_wait(path, timeout=2.0)
        writer.join()
        self.assertIsNotNone(totals)
        self.assertEqual(totals["output_tokens"], 64)

    def test_waiting_gives_up_at_the_timeout(self):
        path = self.transcript([{"type": "attachment"}], "never.jsonl")
        start = time.monotonic()
        self.assertIsNone(
            self.usage.turn_totals_wait(path, timeout=0.2))
        self.assertLess(time.monotonic() - start, 1.0)

    def test_compact_numbers(self):
        self.assertEqual(self.usage.compact(800), "800")
        self.assertEqual(self.usage.compact(5933), "5.9k")
        self.assertEqual(self.usage.compact(31400), "31k")
        self.assertEqual(self.usage.compact(2_400_000), "2.4M")
        self.assertEqual(self.usage.compact(None), "")

    def test_context_is_the_largest_call_not_the_sum(self):
        # Every call in a turn re-reads the conversation, so summing
        # input multiplies the context by the number of calls.
        path = self.transcript(
            [{"type": "user", "message": {"content": "hi"}}]
            + [self.assistant(out=40, inp=300, cache=96000)] * 5)
        totals = self.usage.turn_totals(path)
        self.assertEqual(totals["input_tokens"] + totals["cache_read_tokens"],
                         481500)
        self.assertEqual(totals["context_tokens"], 96300)

    def test_context_counts_cache_creation_too(self):
        path = self.transcript([{"type": "assistant", "message": {
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 100, "output_tokens": 10,
                      "cache_read_input_tokens": 5000,
                      "cache_creation_input_tokens": 2000}}}])
        self.assertEqual(
            self.usage.turn_totals(path)["context_tokens"], 7100)

    def test_last_context_is_the_newest_turn(self):
        for index, context in enumerate((10000, 20000, 30500)):
            self.usage.record(self.session, "p%d" % index,
                              {"output_tokens": 5, "thinking_tokens": 0,
                               "context_tokens": context, "cost_usd": 0.0})
        self.assertEqual(
            self.usage.last_context_tokens(self.session), 30500)

    def test_last_context_is_none_without_a_ledger(self):
        self.assertIsNone(
            self.usage.last_context_tokens("no-such-session"))

    def test_last_thinking_is_the_newest_turn(self):
        for index, thinking in enumerate((900, 40, 2400)):
            self.usage.record(self.session, "p%d" % index,
                              {"output_tokens": 5,
                               "thinking_tokens": thinking,
                               "context_tokens": 100, "cost_usd": 0.0})
        self.assertEqual(
            self.usage.last_thinking_tokens(self.session), 2400)

    def test_money_precision_scales_with_size(self):
        self.assertEqual(self.usage.money(1.7677), "$1.77")
        self.assertEqual(self.usage.money(0.2419), "$0.242")
        self.assertEqual(self.usage.money(0.0066), "$0.0066")
        self.assertEqual(self.usage.money(None), "")

    def test_last_cost_is_the_newest_turn(self):
        for index, cost in enumerate((0.5, 0.25, 0.0123)):
            self.usage.record(self.session, "p%d" % index,
                              {"output_tokens": 5, "thinking_tokens": 1,
                               "context_tokens": 10, "cost_usd": cost})
        self.assertAlmostEqual(
            self.usage.last_cost(self.session), 0.0123)
        # The session total still adds every turn.
        self.assertAlmostEqual(
            self.usage.session_totals(self.session)["cost_usd"], 0.7623)

    def test_last_cost_is_none_without_a_ledger(self):
        self.assertIsNone(self.usage.last_cost("no-such-session"))

    def test_last_thinking_is_none_without_a_ledger(self):
        self.assertIsNone(
            self.usage.last_thinking_tokens("no-such-session"))

    def test_zero_thinking_is_not_shown_as_a_number(self):
        self.usage.record(self.session, "p1",
                          {"output_tokens": 5, "thinking_tokens": 0,
                           "context_tokens": 100, "cost_usd": 0.0})
        self.assertEqual(
            self.usage.last_thinking_tokens(self.session), 0)

    def test_record_then_read_back(self):
        totals = {"output_tokens": 120, "thinking_tokens": 20,
                  "cost_usd": 0.001}
        self.usage.record(self.session, "prompt-1", totals)
        summary = self.usage.session_totals(self.session)
        self.assertEqual(summary["turns"], 1)
        self.assertEqual(summary["output_tokens"], 120)
        self.assertAlmostEqual(summary["cost_usd"], 0.001)

    def test_a_repeated_prompt_id_does_not_double_count(self):
        totals = {"output_tokens": 120, "thinking_tokens": 0,
                  "cost_usd": 0.001}
        self.usage.record(self.session, "prompt-1", totals)
        self.usage.record(self.session, "prompt-1", totals)
        self.assertEqual(
            self.usage.session_totals(self.session)["turns"], 1)

    def test_totals_accumulate_across_turns(self):
        for index, tokens in enumerate((100, 250, 60)):
            self.usage.record(self.session, "p%d" % index,
                              {"output_tokens": tokens,
                               "thinking_tokens": 0, "cost_usd": 0.002})
        summary = self.usage.session_totals(self.session)
        self.assertEqual(summary["turns"], 3)
        self.assertEqual(summary["output_tokens"], 410)
        self.assertAlmostEqual(summary["cost_usd"], 0.006)

    def test_recording_nothing_is_a_no_op(self):
        self.usage.record(self.session, "p1", None)
        self.assertEqual(
            self.usage.session_totals(self.session)["turns"], 0)

    def test_unpriced_turns_leave_the_cost_unset(self):
        self.usage.record(self.session, "p1",
                          {"output_tokens": 10, "thinking_tokens": 0,
                           "cost_usd": None})
        self.assertIsNone(
            self.usage.session_totals(self.session)["cost_usd"])

    def test_a_corrupt_ledger_reads_as_empty(self):
        os.makedirs(self.usage.LEDGER_ROOT, exist_ok=True)
        with open(self.usage.ledger_path(self.session), "w") as f:
            f.write("{not json")
        self.assertEqual(
            self.usage.session_totals(self.session)["turns"], 0)

    def run_stop(self, payload, home, stats="on"):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = home
        claude_dir = os.path.join(home, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        with open(os.path.join(claude_dir, "unclaudish-stats"), "w") as f:
            f.write(stats)
        return subprocess.run([sys.executable, self.LINT_STOP],
                              input=json.dumps(payload).encode(),
                              capture_output=True, env=env, timeout=10)

    def stop_payload(self, path):
        return {"hook_event_name": "Stop", "session_id": self.session,
                "prompt_id": "stop-prompt", "stop_hook_active": False,
                "transcript_path": path,
                "last_assistant_message": "All tests pass."}

    def test_the_stop_hook_records_the_turn(self):
        home = tempfile.mkdtemp(prefix="stop-usage-")
        path = self.transcript([self.assistant(out=300, think=40,
                                               inp=500, cache=2000)])
        self.run_stop(self.stop_payload(path), home)
        summary = self.usage.session_totals(self.session)
        self.assertEqual(summary["output_tokens"], 300)
        self.assertIsNotNone(summary["cost_usd"])
        self.assertEqual(
            self.usage.last_context_tokens(self.session), 2500)
        shutil.rmtree(home, ignore_errors=True)

    def test_recording_survives_mode_off(self):
        # Stats keep their own switch, so the register being off must
        # not stop the accounting.
        home = tempfile.mkdtemp(prefix="stop-usage-off-")
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude",
                               "unclaudish-mode"), "w") as f:
            f.write("off")
        path = self.transcript([self.assistant(out=77)])
        self.run_stop(self.stop_payload(path), home)
        self.assertEqual(
            self.usage.session_totals(self.session)["output_tokens"], 77)
        shutil.rmtree(home, ignore_errors=True)

    def test_nothing_is_recorded_while_stats_are_off(self):
        home = tempfile.mkdtemp(prefix="stop-usage-nostats-")
        path = self.transcript([self.assistant(out=42)])
        self.run_stop(self.stop_payload(path), home, stats="off")
        self.assertEqual(
            self.usage.session_totals(self.session)["turns"], 0)
        shutil.rmtree(home, ignore_errors=True)

    def test_recording_does_not_break_the_linter(self):
        home = tempfile.mkdtemp(prefix="stop-usage-lint-")
        path = self.transcript([self.assistant(out=10)])
        payload = self.stop_payload(path)
        payload["last_assistant_message"] = ("The fix" + EM
                                             + " shipped clean.")
        proc = self.run_stop(payload, home)
        self.assertIn(b"block", proc.stdout)
        shutil.rmtree(home, ignore_errors=True)


class HookWiring(unittest.TestCase):
    """Hooks fail open, so a broken command would ship silently."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "hooks", "hooks.json")) as f:
            self.hooks = json.load(f)["hooks"]

    def commands(self):
        for event, entries in self.hooks.items():
            for entry in entries:
                for hook in entry["hooks"]:
                    yield event, hook

    def resolve(self, command):
        """Strip ${CLAUDE_PLUGIN_ROOT}, quotes, and any argument."""
        path = command.replace('"${CLAUDE_PLUGIN_ROOT}"', REPO_ROOT)
        path = path.replace("${CLAUDE_PLUGIN_ROOT}", REPO_ROOT)
        return path.split(" ")[0].strip('"')

    def test_every_hook_command_exists(self):
        for event, hook in self.commands():
            path = self.resolve(hook["command"])
            self.assertTrue(os.path.isfile(path),
                            "%s points at a missing file: %s"
                            % (event, path))

    def test_every_hook_command_is_executable(self):
        for event, hook in self.commands():
            path = self.resolve(hook["command"])
            self.assertTrue(os.access(path, os.X_OK),
                            "%s is not executable: %s" % (event, path))

    def test_every_hook_script_compiles(self):
        for event, hook in self.commands():
            path = self.resolve(hook["command"])
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", path],
                capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 0,
                             "%s: %s" % (event, proc.stderr[:300]))

    def test_every_hook_declares_a_timeout(self):
        for event, hook in self.commands():
            self.assertIn("timeout", hook, event)

    def test_the_expected_events_are_registered(self):
        for event in ("SessionStart", "ConfigChange", "UserPromptSubmit",
                      "SubagentStart", "Stop", "SubagentStop",
                      "PreToolUse", "MessageDisplay"):
            self.assertIn(event, self.hooks, event)

    def test_scripts_survive_an_empty_payload(self):
        # A hook that crashes on empty stdin would break a session.
        env = dict(os.environ)
        env["HOME"] = tempfile.mkdtemp(prefix="wiring-home-")
        os.makedirs(os.path.join(env["HOME"], ".claude"))
        for event, hook in self.commands():
            command = hook["command"].replace(
                '"${CLAUDE_PLUGIN_ROOT}"', REPO_ROOT).replace('"', "")
            proc = subprocess.run(command.split(), input=b"",
                                  capture_output=True, env=env,
                                  timeout=20)
            self.assertEqual(proc.returncode, 0,
                             "%s exited %d" % (event, proc.returncode))
        shutil.rmtree(env["HOME"], ignore_errors=True)


class StyleNaming(unittest.TestCase):
    """A plugin style is selected by <plugin>:<style>, and a wrong
    name silently selects no style at all."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        with open(os.path.join(REPO_ROOT, ".claude-plugin",
                               "plugin.json")) as f:
            self.manifest = json.load(f)
        self.styles = {}
        styles_dir = os.path.join(REPO_ROOT, "output-styles")
        for name in os.listdir(styles_dir):
            if not name.endswith(".md"):
                continue
            with open(os.path.join(styles_dir, name), encoding="utf-8") as f:
                for line in f:
                    if line.startswith("name:"):
                        self.styles[line.split(":", 1)[1].strip()] = name
                        break

    def test_settings_values_match_the_style_files(self):
        import sync_style
        plugin = self.manifest["name"]
        for mode, value in sync_style.STYLES.items():
            self.assertEqual(value.split(":")[0], plugin, mode)
            style = value.split(":", 1)[1]
            self.assertIn(style, self.styles,
                          "%s names a style no file declares" % mode)

    def test_remind_reads_the_same_style_files(self):
        import remind
        for mode, filename in remind.STYLE_FILES.items():
            path = os.path.join(REPO_ROOT, "output-styles", filename)
            self.assertTrue(os.path.isfile(path), filename)
            self.assertTrue(remind.style_body(mode), mode)

    def test_both_styles_are_reachable(self):
        self.assertEqual(sorted(self.styles),
                         ["unclaudish", "unclaudish-max"])

    def test_no_style_carries_the_force_flag(self):
        # force-for-plugin overrides the user's own choice, which makes
        # the max style unreachable.
        styles_dir = os.path.join(REPO_ROOT, "output-styles")
        for filename in self.styles.values():
            with open(os.path.join(styles_dir, filename),
                      encoding="utf-8") as f:
                self.assertNotIn("force-for-plugin", f.read(), filename)

    def test_manifest_declares_the_styles_directory(self):
        self.assertIn("outputStyles", self.manifest)


class SkillCommands(unittest.TestCase):
    """Each skill tells Claude to run a script; the path it builds has
    to resolve both from the plugin root and from an install."""

    def skill_bodies(self):
        skills_dir = os.path.join(REPO_ROOT, "skills")
        for name in sorted(os.listdir(skills_dir)):
            path = os.path.join(skills_dir, name, "SKILL.md")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    yield name, f.read()

    def test_every_skill_has_frontmatter(self):
        for name, body in self.skill_bodies():
            self.assertTrue(body.startswith("---"), name)
            self.assertIn("name: %s" % name, body)
            self.assertIn("description:", body)

    def test_scripts_named_in_skills_exist(self):
        for name, body in self.skill_bodies():
            for script in re.findall(r"scripts/([a-z_]+\.py)", body):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT, "scripts",
                                                script)),
                    "%s names a missing script: %s" % (name, script))

    def test_the_root_fallback_resolves_an_installed_plugin(self):
        # The skills locate the script through CLAUDE_PLUGIN_ROOT, with
        # a glob over the install cache as the fallback.
        home = tempfile.mkdtemp(prefix="skill-home-")
        cache = os.path.join(home, ".claude", "plugins", "cache",
                             "unclaudish", "unclaudish")
        for version in ("0.1.9", "0.1.10", "0.1.26"):
            os.makedirs(os.path.join(cache, version, "scripts"))
            open(os.path.join(cache, version, "scripts",
                              "sync_style.py"), "w").close()
        script = ('ROOT="${CLAUDE_PLUGIN_ROOT:-$(ls -d'
                  ' "$HOME"/.claude/plugins/cache/*/unclaudish/*'
                  ' 2>/dev/null | sort -V | tail -1)}";'
                  ' echo "$ROOT"')
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        proc = subprocess.run(["bash", "-c", script], capture_output=True,
                              env=env, timeout=10)
        # sort -V picks the newest version, not the lexically last one.
        self.assertEqual(proc.stdout.decode().strip(),
                         os.path.join(cache, "0.1.26"))
        shutil.rmtree(home, ignore_errors=True)

    def test_plugin_root_wins_when_set(self):
        script = ('ROOT="${CLAUDE_PLUGIN_ROOT:-$(ls -d'
                  ' "$HOME"/.claude/plugins/cache/*/unclaudish/*'
                  ' 2>/dev/null | sort -V | tail -1)}";'
                  ' echo "$ROOT"')
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = REPO_ROOT
        proc = subprocess.run(["bash", "-c", script], capture_output=True,
                              env=env, timeout=10)
        self.assertEqual(proc.stdout.decode().strip(), REPO_ROOT)


class ConfigModule(unittest.TestCase):
    """The single source of truth for every switch."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import unclaudish_config
        self.config = unclaudish_config
        self.home = tempfile.mkdtemp(prefix="config-home-")
        os.makedirs(os.path.join(self.home, ".claude"))
        self._real_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        self._reload()

    def tearDown(self):
        if self._real_home is not None:
            os.environ["HOME"] = self._real_home
        os.environ.pop("UNCLAUDISH_DISABLE", None)
        shutil.rmtree(self.home, ignore_errors=True)
        self._reload()

    def _reload(self):
        import importlib
        importlib.reload(self.config)

    def write(self, name, value):
        with open(os.path.join(self.home, ".claude", name), "w") as f:
            f.write(value + "\n")

    def test_mode_defaults_to_on(self):
        self.assertEqual(self.config.read_mode(), "on")

    def test_mode_default_is_configurable(self):
        self.assertIsNone(self.config.read_mode(default=None))

    def test_legacy_mode_value_reads_as_on(self):
        self.write("unclaudish-mode", "unclaudish")
        self.assertEqual(self.config.read_mode(), "on")

    def test_unknown_mode_falls_back(self):
        self.write("unclaudish-mode", "banana")
        self.assertEqual(self.config.read_mode(), "on")

    def test_disabled_follows_mode_off(self):
        self.assertFalse(self.config.disabled())
        self.write("unclaudish-mode", "off")
        self.assertTrue(self.config.disabled())

    def test_env_kill_switch(self):
        os.environ["UNCLAUDISH_DISABLE"] = "1"
        self.assertTrue(self.config.killed())

    def test_file_kill_switch(self):
        open(os.path.join(self.home, ".claude",
                          "unclaudish-off"), "w").close()
        self.assertTrue(self.config.killed())

    def test_subagent_setting_defaults_to_mirror(self):
        self.assertEqual(self.config.subagents_setting(), "mirror")

    def test_subagent_mode_resolution(self):
        cases = [
            ("mirror", "max", "max"), ("mirror", "on", "on"),
            ("on", "max", "on"), ("max", "on", "max"),
            ("off", "max", None), ("mirror", "off", None),
            ("max", "off", None),
        ]
        for setting, mode, expected in cases:
            self.write("unclaudish-subagents", setting)
            self.write("unclaudish-mode", mode)
            self.assertEqual(self.config.subagent_mode(), expected,
                             "%s + %s" % (setting, mode))

    def test_stats_switch_is_independent_of_mode(self):
        self.write("unclaudish-stats", "on")
        self.write("unclaudish-mode", "off")
        self.assertTrue(self.config.stats_enabled())

    def test_stats_default_is_off(self):
        self.assertFalse(self.config.stats_enabled())

    def test_kill_switch_beats_the_stats_flag(self):
        self.write("unclaudish-stats", "on")
        os.environ["UNCLAUDISH_DISABLE"] = "1"
        self.assertFalse(self.config.stats_enabled())

    def test_writes_round_trip(self):
        self.config.write_mode("max")
        self.assertEqual(self.config.read_mode(), "max")
        self.config.write_subagents("max")
        self.assertEqual(self.config.subagents_setting(), "max")


class Robustness(unittest.TestCase):
    def test_fuzz_never_raises(self):
        rng = random.Random(42)
        alphabet = ("ab .!?\n`|>#*-" + EM + EN + CURLY +
                    "￿\U0001f600$\\")
        for _ in range(200):
            text = "".join(
                rng.choice(alphabet)
                for _ in range(rng.randrange(0, 400))
            )
            result = cc.evaluate(text)
            self.assertIn(result["verdict"], ("pass", "block"))

    def test_performance_50kb_under_200ms(self):
        text = ("The deploy pipeline builds, tests, and publishes the "
                "image. " * 800)[:50000]
        start = time.monotonic()
        cc.evaluate(text)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.2, "evaluate too slow: %.3fs" % elapsed)


class LintStopProcess(unittest.TestCase):
    """Fault injection and contract tests for the hook entry point."""

    def setUp(self):
        self.state_dir = os.path.join(tempfile.gettempdir(),
                                      "unclaudish-state")
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def run_hook(self, stdin_bytes, env_extra=None, mode=None):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        # Hermetic HOME so the developer's real mode/kill flags never
        # leak into test outcomes.
        self.home = getattr(self, "home", None) or \
            tempfile.mkdtemp(prefix="lint-home-")
        env["HOME"] = self.home
        claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        mode_path = os.path.join(claude_dir, "unclaudish-mode")
        if mode is None and os.path.exists(mode_path):
            os.unlink(mode_path)
        elif mode is not None:
            with open(mode_path, "w") as f:
                f.write(mode)
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, LINT_STOP],
            input=stdin_bytes, capture_output=True, env=env, timeout=10,
        )
        return proc

    def hook_json(self, message, prompt_id="t1", active=False):
        return json.dumps({
            "hook_event_name": "Stop",
            "prompt_id": prompt_id,
            "stop_hook_active": active,
            "transcript_path": "/nonexistent/transcript.jsonl",
            "last_assistant_message": message,
        }).encode()

    def test_blocks_on_hard_violation(self):
        proc = self.run_hook(self.hook_json("Fix" + EM + "shipped."))
        self.assertEqual(proc.returncode, 0)
        output = json.loads(proc.stdout)
        self.assertEqual(output["decision"], "block")
        self.assertIn("em_dash", output["reason"])
        self.assertIn("Do not add or drop information",
                      output["reason"].replace("\n", " "))

    def test_allows_clean_message(self):
        proc = self.run_hook(self.hook_json("The tests pass."))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), b"")

    def test_blocks_only_once_per_prompt(self):
        first = self.run_hook(self.hook_json("A" + EM + "B", "p9"))
        second = self.run_hook(self.hook_json("A" + EM + "B", "p9"))
        self.assertIn(b"block", first.stdout)
        self.assertEqual(second.stdout.strip(), b"")

    def test_respects_stop_hook_active(self):
        proc = self.run_hook(self.hook_json("A" + EM + "B", active=True))
        self.assertEqual(proc.stdout.strip(), b"")

    def test_mode_off_disables_linter(self):
        payload = self.hook_json("A" + EM + "B", "poff")
        proc = self.run_hook(payload, mode="off")
        self.assertEqual(proc.stdout.strip(), b"")

    def test_kill_switch_env(self):
        proc = self.run_hook(self.hook_json("A" + EM + "B"),
                             {"UNCLAUDISH_DISABLE": "1"})
        self.assertEqual(proc.stdout.strip(), b"")

    def test_fail_open_on_garbage_stdin(self):
        for payload in [b"", b"not json", b"\x00\xff\xfe",
                        b"[]", b'{"unrelated": true}']:
            proc = self.run_hook(payload)
            self.assertEqual(proc.returncode, 0,
                             "non-zero exit on %r" % payload)

    def test_transcript_turn_reassembly(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            entries = [
                {"type": "user", "message": {"content": "do the task"}},
                {"type": "assistant", "message": {"content": [
                    {"type": "text",
                     "text": "Part one" + EM + "with a dash."}]}},
                {"type": "user", "message": {"content": [
                    {"type": "tool_result", "content": "ok"}]}},
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "Part two is clean."}]}},
            ]
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
            transcript = f.name
        try:
            payload = json.dumps({
                "hook_event_name": "Stop",
                "prompt_id": "t-multi",
                "stop_hook_active": False,
                "transcript_path": transcript,
                "last_assistant_message": "Part two is clean.",
            }).encode()
            proc = self.run_hook(payload)
            # The dash is in part one, which only transcript parsing
            # can see; last_assistant_message alone would miss it.
            self.assertIn(b"block", proc.stdout)
        finally:
            os.unlink(transcript)


class StyleSync(unittest.TestCase):
    """The mode flag and the global outputStyle must stay in step.

    Probe-verified: a plugin style is only selected by its namespaced
    name, so a bare "unclaudish-max" in settings selects nothing.
    """

    SYNC = os.path.join(REPO_ROOT, "scripts", "sync_style.py")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sync-home-")
        self.claude_dir = os.path.join(self.home, ".claude")
        os.makedirs(self.claude_dir)
        self.settings = os.path.join(self.claude_dir, "settings.json")
        self.mode_file = os.path.join(self.claude_dir,
                                      "unclaudish-mode")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_sync(self, *args, stdin=b""):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        env["HOME"] = self.home
        return subprocess.run([sys.executable, self.SYNC] + list(args),
                              input=stdin, capture_output=True,
                              env=env, timeout=10)

    def write_settings(self, data):
        with open(self.settings, "w") as f:
            json.dump(data, f)

    def read_settings(self):
        with open(self.settings) as f:
            return json.load(f)

    def read_mode(self):
        with open(self.mode_file) as f:
            return f.read().strip()

    def test_set_max_writes_namespaced_style(self):
        self.write_settings({"model": "opus"})
        self.run_sync("set", "max")
        data = self.read_settings()
        self.assertEqual(data["outputStyle"], "unclaudish:unclaudish-max")
        self.assertEqual(data["model"], "opus")  # nothing else touched
        self.assertEqual(self.read_mode(), "max")

    def test_set_on_writes_namespaced_style(self):
        self.run_sync("set", "on")
        self.assertEqual(self.read_settings()["outputStyle"],
                         "unclaudish:unclaudish")

    def test_set_creates_settings_when_missing(self):
        self.run_sync("set", "on")
        self.assertTrue(os.path.exists(self.settings))

    def test_off_removes_our_style_only(self):
        self.write_settings({"outputStyle": "unclaudish:unclaudish-max",
                             "model": "opus"})
        self.run_sync("set", "off")
        data = self.read_settings()
        self.assertNotIn("outputStyle", data)
        self.assertEqual(data["model"], "opus")
        self.assertEqual(self.read_mode(), "off")

    def test_off_leaves_a_foreign_style_alone(self):
        self.write_settings({"outputStyle": "Explanatory"})
        self.run_sync("set", "off")
        self.assertEqual(self.read_settings()["outputStyle"],
                         "Explanatory")

    def test_malformed_settings_are_never_clobbered(self):
        with open(self.settings, "w") as f:
            f.write("{not json")
        self.run_sync("set", "max")
        with open(self.settings) as f:
            self.assertEqual(f.read(), "{not json")
        self.assertEqual(self.read_mode(), "max")  # flag still works

    def test_reconcile_fills_missing_style_for_fresh_install(self):
        self.write_settings({"model": "opus"})
        self.run_sync("reconcile")
        self.assertEqual(self.read_settings()["outputStyle"],
                         "unclaudish:unclaudish")
        self.assertEqual(self.read_mode(), "on")

    def test_reconcile_honors_the_mode_flag(self):
        with open(self.mode_file, "w") as f:
            f.write("max\n")
        self.write_settings({})
        self.run_sync("reconcile")
        self.assertEqual(self.read_settings()["outputStyle"],
                         "unclaudish:unclaudish-max")

    def test_reconcile_follows_a_style_picked_in_config(self):
        with open(self.mode_file, "w") as f:
            f.write("on\n")
        self.write_settings({"outputStyle": "unclaudish:unclaudish-max"})
        self.run_sync("reconcile")
        self.assertEqual(self.read_mode(), "max")

    def test_reconcile_respects_off(self):
        with open(self.mode_file, "w") as f:
            f.write("off\n")
        self.write_settings({"model": "opus"})
        self.run_sync("reconcile")
        self.assertNotIn("outputStyle", self.read_settings())

    def test_reconcile_leaves_foreign_styles_alone(self):
        self.write_settings({"outputStyle": "Explanatory"})
        self.run_sync("reconcile")
        self.assertEqual(self.read_settings()["outputStyle"],
                         "Explanatory")
        self.assertFalse(os.path.exists(self.mode_file))

    def test_reconcile_ignores_hook_payload_on_stdin(self):
        payload = json.dumps({"hook_event_name": "SessionStart",
                              "source": "startup"}).encode()
        proc = self.run_sync("reconcile", stdin=payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), b"")
        self.assertEqual(self.read_settings()["outputStyle"],
                         "unclaudish:unclaudish")

    def test_reconcile_skipped_by_kill_switch(self):
        open(os.path.join(self.claude_dir, "unclaudish-off"), "w").close()
        self.write_settings({})
        self.run_sync("reconcile")
        self.assertNotIn("outputStyle", self.read_settings())

    def test_status_reports_without_changing_anything(self):
        self.write_settings({"outputStyle": "unclaudish:unclaudish"})
        proc = self.run_sync("status")
        self.assertIn(b"unclaudish:unclaudish", proc.stdout)
        self.assertIn(b"subagents: mirror", proc.stdout)
        self.assertFalse(os.path.exists(self.mode_file))

    def test_hooks_registered_for_startup_and_config_change(self):
        with open(os.path.join(REPO_ROOT, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        for event in ("SessionStart", "ConfigChange"):
            command = hooks[event][0]["hooks"][0]["command"]
            self.assertIn("sync_style.py reconcile", command, event)

    def test_reconcile_is_idempotent(self):
        # ConfigChange fires when settings change, including our own
        # write, so a second pass must produce no further write.
        self.write_settings({"model": "opus"})
        self.run_sync("reconcile")
        first = os.stat(self.settings).st_mtime_ns
        self.run_sync("reconcile")
        self.assertEqual(os.stat(self.settings).st_mtime_ns, first)

    def test_no_style_file_forces_itself_on_the_user(self):
        # force-for-plugin overrides an explicit setting, which would
        # make the max style unreachable.
        styles_dir = os.path.join(REPO_ROOT, "output-styles")
        for name in os.listdir(styles_dir):
            with open(os.path.join(styles_dir, name)) as f:
                self.assertNotIn("force-for-plugin", f.read(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
