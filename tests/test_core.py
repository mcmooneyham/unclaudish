"""Unit tests for claudish_core and lint_stop.

Detection fixtures are built at runtime from unicode escapes so no
source file contains a literal em dash. Run:
    python3 tests/test_core.py -v
"""

import json
import os
import random
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

    def test_genuine_concession_not_blocked(self):
        self.assert_clean("You're right, the limit is 100, not 1000.")

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

    def test_bold_term_list_detected(self):
        text = ("- **Speed:** fast.\n- **Cost:** low.\n"
                "- **Risk:** none.\n" + PAD)
        self.assertIn("bold_term_list", cc.evaluate(text)["metrics"])

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

    def run_hook(self, payload):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
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

    def test_fail_open_on_garbage(self):
        for payload in (b"", b"not json", b"[]"):
            proc = self.run_hook(payload)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout.strip(), b"")


class RemindModes(unittest.TestCase):
    REMIND = os.path.join(REPO_ROOT, "scripts", "remind.sh")

    def run_remind(self, mode):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
        with tempfile.TemporaryDirectory() as home:
            env["HOME"] = home
            if mode is not None:
                claude_dir = os.path.join(home, ".claude")
                os.makedirs(claude_dir)
                with open(os.path.join(claude_dir,
                                       "unclaudish-mode"), "w") as f:
                    f.write(mode + "\n")
            return subprocess.run(["bash", self.REMIND],
                                  capture_output=True, env=env,
                                  timeout=10).stdout

    def test_default_mode(self):
        out = self.run_remind(None)
        self.assertIn(b"plain natural language", out)

    def test_on_mode(self):
        out = self.run_remind("on")
        self.assertIn(b"plain natural language", out)

    def test_legacy_flag_value_treated_as_on(self):
        out = self.run_remind("unclaudish")
        self.assertIn(b"plain natural language", out)

    def test_max_mode(self):
        out = self.run_remind("max")
        self.assertIn(b"unclaudish-max", out)
        self.assertIn(b"Under 60 words", out)

    def test_off_mode_silent(self):
        self.assertEqual(self.run_remind("off").strip(), b"")


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

    def run_hook(self, stdin_bytes, env_extra=None):
        env = dict(os.environ)
        env.pop("UNCLAUDISH_DISABLE", None)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
