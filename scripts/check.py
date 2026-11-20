"""Complete local verification; fails if GTK/display tests cannot run.

Usage: python3 scripts/check.py [--screenshots /tmp/timebook-ui]
Uses temporary databases and never reads personal usage history.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def screenshots(output: Path) -> None:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkX11", "4.0")
    from gi.repository import Adw, GdkX11, Gio, GLib, Gtk
    from timebook.core.store import Store
    from timebook.core.forfeit import ForfeitStore
    from timebook.core.l10n import set_language
    from timebook.ui.main_window import MainWindow, PAGES
    from timebook.ui.theme import install_css
    from timebook.ui.overlay import BreakOverlay
    from tests.test_regressions import context
    from scripts.demo_seed import seed

    if not Gtk.init_check():
        raise RuntimeError("Screenshot verification requires a display")
    Adw.init()
    app = Adw.Application(application_id="io.github.timebook.VisualCheck", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    install_css()
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    original_hook = sys.excepthook
    sys.excepthook = lambda *error: errors.append(str(error[1]))

    def drain():
        loop = GLib.MainContext.default()
        end = time.monotonic() + 0.28
        while time.monotonic() < end:
            while loop.pending():
                loop.iteration(False)
            time.sleep(0.005)

    def capture(window, name):
        drain()
        xid = window.get_surface().get_xid()
        path = output / f"{name}.png"
        subprocess.run(["import", "-window", str(xid), str(path)], check=True, timeout=15)
        if not path.exists() or path.stat().st_size < 1000:
            raise RuntimeError(f"Empty screenshot: {path}")
        if errors:
            raise RuntimeError(f"GTK drawing/signal errors: {errors}")

    ctx, _, _ = context()
    window = None
    try:
        with tempfile.TemporaryDirectory(prefix="timebook-visual-") as temp:
            db = Path(temp) / "demo.db"
            seed(str(db), days=30)
            source = Store(db)
            # Copy the demo database into the isolated context's in-memory DB.
            source._conn.backup(ctx.store._conn)
            source.close()
            ctx.forfeit = ForfeitStore(ctx.store)
        set_language("zh")
        window = MainWindow(app, ctx)
        window.present()
        manager = Adw.StyleManager.get_default()
        for theme, scheme in (("light", Adw.ColorScheme.FORCE_LIGHT), ("dark", Adw.ColorScheme.FORCE_DARK)):
            manager.set_color_scheme(scheme)
            window.set_default_size(1020, 760)
            for key, *_ in PAGES:
                window.show_page(key)
                capture(window, f"{key}-{theme}")
            stats = window.stack.get_child_by_name("stats")
            stats.month_button.set_active(True)
            window.show_page("stats")
            capture(window, f"stats-month-{theme}")
            stats.week_button.set_active(True)
            window.set_default_size(860, 600)
            window.show_page("focus")
            capture(window, f"focus-compact-{theme}")
        window._open_settings()
        capture(window._settings_window, "settings-dark")
        window._settings_window.close()
        overlay = BreakOverlay(app, duration=20)
        overlay.present()
        geometry = overlay._monitor.get_geometry()
        deadline = time.monotonic() + 3
        while (not overlay.is_fullscreen() or overlay.get_width() != geometry.width
               or overlay.get_height() != geometry.height) and time.monotonic() < deadline:
            drain()
        if not overlay.is_fullscreen() or overlay.get_height() != geometry.height:
            raise RuntimeError("Micro-break did not cover its monitor")
        capture(overlay, "overlay-dark")
        overlay.close()
        set_language("en")
        window.refresh(force=True)
        for key, *_ in PAGES:
            window.show_page(key)
            capture(window, f"{key}-en-compact")
        window._open_settings()
        capture(window._settings_window, "settings-en")
        window._settings_window.close()
        manifest = {"images": sorted(p.name for p in output.glob("*.png")),
                    "sizes": [[1020, 760], [860, 600]], "themes": ["light", "dark"], "languages": ["zh", "en"],
                    "render_errors": errors}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    finally:
        if window:
            if window._settings_window:
                window._settings_window.destroy()
            window.destroy()
        ctx.store.close()
        sys.excepthook = original_hook


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path, help="Capture all pages in both themes (X11 + ImageMagick)")
    args = parser.parse_args()
    os.environ.update(TIMEBOOK_REQUIRE_UI="1", GSK_RENDERER="cairo", GIO_USE_VFS="local",
                      ADW_DISABLE_PORTAL="1")
    # Do not start system accessibility daemons during repeated test windows.
    os.environ.setdefault("GTK_A11Y", "none")
    commands = [
        [sys.executable, "-m", "compileall", "-q", "timebook", "tests", "scripts"],
        ["bash", "-n", "install.sh", "run.sh"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    ]
    for command in commands:
        print("Running:", " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    if args.screenshots:
        screenshots(args.screenshots.resolve())
        print(f"Screenshots: {args.screenshots.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
