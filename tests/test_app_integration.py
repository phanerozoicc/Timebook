"""CLI startup -> real application -> dump/exported UI -> graceful shutdown."""
import json
import itertools
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_ui import GUI
from timebook.core.store import Store

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(GUI, "Needs GTK display")
class ApplicationIntegrationTests(unittest.TestCase):
    def test_cli_starts_each_page_and_exits_without_tracking(self):
        for language, page in itertools.product(("zh", "en"), ("today", "focus", "stats", "timeline", "forfeit")):
            with self.subTest(language=language, page=page), tempfile.TemporaryDirectory(prefix="timebook-app-test-") as tmp:
                root = Path(tmp)
                db = root / "test.db"
                with Store(db) as store:
                    store.set("language", language)
                    store.set("trayEnabled", False)
                env = dict(os.environ, GSK_RENDERER="cairo", GTK_A11Y="none", ADW_DISABLE_PORTAL="1",
                           GIO_USE_VFS="local", XDG_DATA_HOME=str(root / "data"),
                           XDG_STATE_HOME=str(root / "state"))
                target = root / "state.json"
                result = subprocess.run(
                    [sys.executable, "-m", "timebook.main",
                     "--db", str(db), "--no-track", "--page", page, "--dump", str(target)],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=25,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("CRITICAL", result.stderr)
                state = json.loads(target.read_text())
                self.assertEqual(state["page"], page)
                if language == "en":
                    self.assertFalse(any(re.search(r"[\u3400-\u9fff]", text) for text in state["widget_texts"]), state["widget_texts"])
                self.assertEqual(state["today_rows"], 0)
                self.assertGreater(state["widget_count"], 20)
                self.assertGreaterEqual(state["layout_width"], 860)
                with Store(db) as store:
                    self.assertEqual(store.count_events(), 0)
                self.assertFalse((root / "data/timebook/widget-snapshot.json").exists())
