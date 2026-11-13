"""Standalone FromSoftware troubleshooter."""

from __future__ import annotations

import os
import platform
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import pyperclip

from fromsoftware_troubleshooter import __version__
from fromsoftware_troubleshooter.checker import (
    ArmoredCore6Checker,
    BaseChecker,
    DarkSouls1Checker,
    DarkSouls2Checker,
    DarkSouls3Checker,
    DiagnosticResult,
    EldenRingChecker,
    NightReignChecker,
    SekiroChecker,
    clear_caches,
    find_game_folder,
    get_linux_launch_options,
    permission_fix_commands,
    run_check,
)

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------
COLORS = {
    "bg": "#1e1e2e",
    "bg_alt": "#181825",
    "surface": "#313244",
    "surface_alt": "#45475a",
    "fg": "#cdd6f4",
    "fg_muted": "#a6adc8",
    "accent": "#cba6f7",  # Mauve
    "accent_hover": "#b490e3",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "red": "#f38ba8",
    "blue": "#89b4fa",
}

STATUS_COLORS = {
    "ok": COLORS["green"],
    "warning": COLORS["yellow"],
    "error": COLORS["red"],
    "info": COLORS["blue"],
}

STATUS_ICONS = {"ok": "OK", "warning": "!", "error": "X", "info": "i"}

GAME_OPTIONS: dict[str, type] = {
    "Elden Ring": EldenRingChecker,
    "Elden Ring Nightreign": NightReignChecker,
    "Dark Souls Remastered": DarkSouls1Checker,
    "Dark Souls II: Scholar of the First Sin": DarkSouls2Checker,
    "Dark Souls III": DarkSouls3Checker,
    "Sekiro: Shadows Die Twice": SekiroChecker,
    "Armored Core VI: Fires of Rubicon": ArmoredCore6Checker,
}

GAME_MANIFEST_KEYS: dict[str, str] = {
    "Elden Ring": "elden_ring",
    "Elden Ring Nightreign": "nightreign",
    "Dark Souls Remastered": "dark_souls_remastered",
    "Dark Souls II: Scholar of the First Sin": "dark_souls_2",
    "Dark Souls III": "dark_souls_3",
    "Sekiro: Shadows Die Twice": "sekiro",
    "Armored Core VI: Fires of Rubicon": "armored_core_6",
}

# Order in which installed games are looked for at startup.
DEFAULT_GAME_ORDER = [
    "Elden Ring",
    "Elden Ring Nightreign",
    "Dark Souls III",
    "Dark Souls Remastered",
    "Dark Souls II: Scholar of the First Sin",
    "Sekiro: Shadows Die Twice",
    "Armored Core VI: Fires of Rubicon",
]

_SENTINEL = object()


# ---------------------------------------------------------------------------
# Permission fix dialog
# ---------------------------------------------------------------------------


def _show_permission_fix(
    parent: ctk.CTk, game_folder: Path | None, game_exe: str, manifest_key: str
) -> None:
    dialog = ctk.CTkToplevel(parent)
    dialog.title("Fix Steam Permissions")
    dialog.resizable(False, False)
    dialog.configure(fg_color=COLORS["bg"])
    dialog.lift()
    dialog.attributes("-topmost", True)

    w, h = 650, 520
    parent.update_idletasks()
    px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
    py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
    dialog.geometry(f"{w}x{h}+{px}+{py}")
    dialog.after(50, dialog.grab_set)

    inner = ctk.CTkScrollableFrame(
        dialog, fg_color=COLORS["bg"], scrollbar_button_color=COLORS["surface"]
    )
    inner.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(
        inner,
        text="Fix Steam/Game Permission Issues",
        font=("Segoe UI", 16, "bold"),
        text_color=COLORS["fg"],
    ).pack(anchor="w", pady=(0, 10))

    ctk.CTkLabel(
        inner,
        text="Follow these steps if you're getting error 740 or permission errors:",
        font=("Segoe UI", 11),
        text_color=COLORS["fg_muted"],
    ).pack(anchor="w", pady=(0, 15))

    steps = [
        "1. Exit Steam completely",
        "2. Right-click steam.exe > Properties > Compatibility tab",
        "   → Uncheck 'Run this program as an administrator'",
        f"3. Right-click {game_exe} in game folder > Properties > Compatibility tab",
        "   → Uncheck 'Run this program as an administrator'",
        "4. Take Ownership (PowerShell as Admin):",
    ]

    for step in steps:
        ctk.CTkLabel(
            inner,
            text=step,
            font=("Segoe UI", 11),
            text_color=COLORS["fg"],
            anchor="w",
        ).pack(anchor="w", pady=2)

    for command in permission_fix_commands(game_folder, manifest_key):
        box = ctk.CTkTextbox(
            inner,
            height=28,
            font=("Consolas", 10),
            wrap="none",
            fg_color=COLORS["surface"],
            text_color=COLORS["fg"],
        )
        box.pack(fill="x", pady=2)
        box.insert("1.0", command)
        box.configure(state="disabled")

    ctk.CTkLabel(
        inner,
        text="5. If issues persist:",
        font=("Segoe UI", 11),
        text_color=COLORS["fg"],
        anchor="w",
    ).pack(anchor="w", pady=(15, 2))

    ctk.CTkLabel(
        inner,
        text="   • Reinstall Steam (download the installer from steampowered.com and run)",
        font=("Segoe UI", 11),
        text_color=COLORS["fg_muted"],
        anchor="w",
    ).pack(anchor="w", pady=2)

    if game_folder:
        reinstall_text = "   • OR: In Steam, uninstall the game, then manually delete the entire Game folder at:"
        ctk.CTkLabel(
            inner,
            text=reinstall_text,
            font=("Segoe UI", 11),
            text_color=COLORS["fg_muted"],
            anchor="w",
        ).pack(anchor="w", pady=2)

        ctk.CTkLabel(
            inner,
            text=f"     {game_folder}",
            font=("Segoe UI", 11),
            text_color=COLORS["fg_muted"],
            anchor="w",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 2))

        ctk.CTkLabel(
            inner,
            text="     Then restart Steam and reinstall the game",
            font=("Segoe UI", 11),
            text_color=COLORS["fg_muted"],
            anchor="w",
        ).pack(anchor="w", pady=(0, 2))
    else:
        ctk.CTkLabel(
            inner,
            text="   • OR: In Steam, uninstall game, manually delete game folder, reinstall",
            font=("Segoe UI", 11),
            text_color=COLORS["fg_muted"],
            anchor="w",
        ).pack(anchor="w", pady=2)

    ctk.CTkButton(
        dialog,
        text="Close",
        width=100,
        command=dialog.destroy,
        fg_color=COLORS["surface"],
        hover_color=COLORS["surface_alt"],
        text_color=COLORS["fg"],
    ).pack(pady=(0, 20))


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class TroubleshooterApp:
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(f"FromSoftware Troubleshooter {__version__}")
        self.root.geometry("740x660")
        self.root.resizable(True, True)
        self.root.configure(fg_color=COLORS["bg"])

        # Set icon if available
        # Frozen builds unpack bundled data to sys._MEIPASS; from source the
        # icon sits in the project root.
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        icon_path = base / "icon.png"
        if icon_path.exists():
            try:
                icon_img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, icon_img)
            except Exception:
                pass

        self._game_var = ctk.StringVar()
        self._game_folder: Path | None = None
        self._linux_launch_options_btn: ctk.CTkButton | None = None
        self._check_thread: threading.Thread | None = None
        self._current_results: list[DiagnosticResult] = []
        # Incremented per game scan; a finished scan with an older token is
        # stale because the game was switched in the meantime.
        self._scan_token = 0

        self._build_ui()
        self._game_var.set(DEFAULT_GAME_ORDER[0])
        self._start_initial_scan()

    def _in_background(self, work, on_done) -> None:
        """Run work() on a thread, then on_done(result) on the Tk thread."""
        holder: dict = {}

        def target() -> None:
            try:
                holder["result"] = work()
            except Exception:
                holder["result"] = None

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

        def poll() -> None:
            if thread.is_alive():
                self.root.after(30, poll)
            else:
                on_done(holder.get("result"))

        self.root.after(30, poll)

    def _new_scan(self) -> int:
        self._scan_token += 1
        self._game_folder_label.configure(
            text="Scanning...", text_color=COLORS["fg_muted"]
        )
        return self._scan_token

    def _start_initial_scan(self) -> None:
        """Select the first installed game in DEFAULT_GAME_ORDER."""
        token = self._new_scan()

        def work() -> tuple[str, Path] | None:
            for game_name in DEFAULT_GAME_ORDER:
                folder = find_game_folder(GAME_MANIFEST_KEYS[game_name])
                if folder:
                    return game_name, folder
            return None

        def done(found: tuple[str, Path] | None) -> None:
            if token != self._scan_token:
                return
            if found:
                self._game_var.set(found[0])
            self._apply_game_folder(found[1] if found else None)

        self._in_background(work, done)

    def _build_ui(self) -> None:
        main = ctk.CTkFrame(self.root, fg_color=COLORS["bg"])
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            header,
            text="FromSoftware Troubleshooter",
            font=("Segoe UI", 18, "bold"),
            text_color=COLORS["fg"],
        ).pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            header,
            text="Refresh",
            command=self._run_checks,
            width=90,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_alt"],
            text_color=COLORS["fg"],
        )
        self._refresh_btn.pack(side="right", padx=(8, 0))

        ctk.CTkOptionMenu(
            header,
            variable=self._game_var,
            values=list(GAME_OPTIONS.keys()),
            command=lambda _: self._on_game_changed(),
            width=290,
            fg_color=COLORS["surface"],
            button_color=COLORS["surface_alt"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["bg_alt"],
            dropdown_hover_color=COLORS["surface"],
            text_color=COLORS["fg"],
        ).pack(side="right")

        # Game folder row
        folder_row = ctk.CTkFrame(main, fg_color="transparent")
        folder_row.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            folder_row,
            text="Set Game Folder",
            command=self._pick_game_folder,
            width=140,
            fg_color=COLORS["surface"],
            hover_color=COLORS["accent"],
            text_color=COLORS["fg"],
        ).pack(side="left", padx=(0, 10))

        if os.name == "nt":
            ctk.CTkButton(
                folder_row,
                text="Fix Permissions",
                command=self._show_perm_fix,
                width=140,
                fg_color=COLORS["surface"],
                hover_color=COLORS["accent"],
                text_color=COLORS["fg"],
            ).pack(side="left", padx=(0, 10))
        elif platform.system() == "Linux":
            self._linux_launch_options_btn = ctk.CTkButton(
                folder_row,
                text="Copy Linux Launch Options",
                command=self._copy_linux_launch_options,
                width=190,
                fg_color=COLORS["surface"],
                hover_color=COLORS["accent"],
                text_color=COLORS["fg"],
                state="disabled",
            )
            self._linux_launch_options_btn.pack(side="left", padx=(0, 10))

        self._game_folder_label = ctk.CTkLabel(
            folder_row,
            text="Scanning...",
            font=("Segoe UI", 11),
            text_color=COLORS["fg_muted"],
            anchor="w",
        )
        self._game_folder_label.pack(side="left", fill="x", expand=True)

        # Progress bar
        self._progress = ctk.CTkProgressBar(
            main,
            mode="indeterminate",
            height=4,
            fg_color=COLORS["surface"],
            progress_color=COLORS["accent"],
        )
        self._progress.pack(fill="x", pady=(0, 6))
        self._progress.pack_forget()

        # Results header (summary + copy button)
        results_header = ctk.CTkFrame(main, fg_color="transparent")
        results_header.pack(fill="x", pady=(0, 4))

        self._summary_label = ctk.CTkLabel(
            results_header,
            text="",
            font=("Segoe UI", 11),
            text_color=COLORS["fg_muted"],
            anchor="w",
        )
        self._summary_label.pack(side="left")

        self._copy_btn = ctk.CTkButton(
            results_header,
            text="Copy to Clipboard",
            width=130,
            height=26,
            command=self._copy_results_to_clipboard,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_alt"],
            text_color=COLORS["fg"],
            font=("Segoe UI", 11),
        )
        self._copy_btn.pack(side="right")
        self._copy_btn.pack_forget()  # Hidden until results exist

        # Results
        self.results_frame = ctk.CTkScrollableFrame(
            main,
            corner_radius=8,
            fg_color=COLORS["bg_alt"],
            scrollbar_button_color=COLORS["surface"],
            scrollbar_button_hover_color=COLORS["accent"],
        )
        self.results_frame.pack(fill="both", expand=True, pady=(0, 10))

        ctk.CTkButton(
            main,
            text="Close",
            command=self.root.destroy,
            width=100,
            fg_color=COLORS["surface"],
            hover_color=COLORS["red"],
            text_color=COLORS["fg"],
        ).pack(pady=(5, 0))

    # -------------------------------------------------------------------------

    def _on_game_changed(self) -> None:
        key = GAME_MANIFEST_KEYS.get(self._game_var.get())
        token = self._new_scan()

        def done(folder: Path | None) -> None:
            if token == self._scan_token:
                self._apply_game_folder(folder)

        self._in_background(lambda: find_game_folder(key) if key else None, done)

    def _apply_game_folder(self, folder: Path | None) -> None:
        self._game_folder = folder
        if folder:
            self._game_folder_label.configure(text=str(folder), text_color=COLORS["fg"])
        else:
            self._game_folder_label.configure(
                text="Not found automatically. Use Set Game Folder.",
                text_color=COLORS["yellow"],
            )
        self._update_linux_launch_options_button()
        self._run_checks()

    def _pick_game_folder(self) -> None:
        folder = filedialog.askdirectory(
            title=f"Select {self._game_var.get()} installation folder",
            parent=self.root,
        )
        if not folder:
            return
        picked = Path(folder)
        checker_cls = GAME_OPTIONS.get(self._game_var.get(), EldenRingChecker)
        subfolder = checker_cls.GAME_SUBFOLDER
        exe_name = checker_cls.EXE_NAME
        # If the picked folder is already the Game subfolder itself (exe sits
        # directly inside it) rather than its parent, back up one level so
        # GAME_SUBFOLDER isn't appended a second time, which would otherwise
        # look for a nonexistent nested Game/Game path.
        if (
            subfolder
            and exe_name
            and not (picked / subfolder / exe_name).exists()
            and (picked / exe_name).exists()
        ):
            picked = picked.parent
        # A scan still running for this game must not replace the choice.
        self._scan_token += 1
        self._apply_game_folder(picked)

    def _update_linux_launch_options_button(self) -> None:
        if self._linux_launch_options_btn is None:
            return
        manifest_key = GAME_MANIFEST_KEYS.get(self._game_var.get())
        options = get_linux_launch_options(manifest_key or "", self._game_folder)
        self._linux_launch_options_btn.configure(
            state="normal" if options else "disabled"
        )

    def _copy_linux_launch_options(self) -> None:
        manifest_key = GAME_MANIFEST_KEYS.get(self._game_var.get())
        options = get_linux_launch_options(manifest_key or "", self._game_folder)
        if not options or self._linux_launch_options_btn is None:
            return
        try:
            pyperclip.copy(options)
        except Exception:
            self.root.clipboard_clear()
            self.root.clipboard_append(options)
            self.root.update()
        self._linux_launch_options_btn.configure(text="Copied!")
        self.root.after(
            1500,
            lambda: (
                self._linux_launch_options_btn
                and self._linux_launch_options_btn.configure(
                    text="Copy Linux Launch Options"
                )
            ),
        )

    def _show_perm_fix(self) -> None:
        checker_cls = GAME_OPTIONS.get(self._game_var.get(), EldenRingChecker)
        game_exe = checker_cls.EXE_NAME
        _show_permission_fix(
            self.root, self._game_folder, game_exe, checker_cls.MANIFEST_KEY
        )

    # -------------------------------------------------------------------------

    def _run_checks(self) -> None:
        clear_caches()
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        self._progress.pack(fill="x", pady=(0, 6))
        self._progress.start()
        self._refresh_btn.configure(state="disabled")

        checker_cls = GAME_OPTIONS.get(self._game_var.get(), EldenRingChecker)
        checker = checker_cls(game_folder=self._game_folder)

        self._current_results = []

        # Each run gets its own queue, so results of a superseded run that is
        # still finishing never reach the new one.
        result_queue: queue.Queue = queue.Queue()
        thread = threading.Thread(
            target=self._check_worker,
            args=(checker, result_queue),
            daemon=True,
        )
        self._check_thread = thread
        thread.start()
        self.root.after(50, lambda: self._poll_results(thread, result_queue))

    def _check_worker(self, checker: BaseChecker, q: queue.Queue) -> None:
        try:
            for name, check in checker.checks():
                for result in run_check(name, check):
                    q.put(result)
        finally:
            q.put(_SENTINEL)

    def _poll_results(self, thread: threading.Thread, q: queue.Queue) -> None:
        if thread is not self._check_thread:
            return
        try:
            while True:
                item = q.get_nowait()
                if item is _SENTINEL:
                    self._progress.stop()
                    self._progress.pack_forget()
                    self._refresh_btn.configure(state="normal")
                    self._update_summary()
                    return
                self._current_results.append(item)
                self._create_result_widget(item)
        except queue.Empty:
            pass
        self.root.after(50, lambda: self._poll_results(thread, q))

    # -------------------------------------------------------------------------

    def _create_result_widget(self, result: DiagnosticResult) -> None:
        color = STATUS_COLORS.get(result.status, COLORS["blue"])
        icon = STATUS_ICONS.get(result.status, "i")

        card = ctk.CTkFrame(
            self.results_frame,
            corner_radius=8,
            fg_color=COLORS["surface"],
        )
        card.pack(fill="x", padx=4, pady=4)

        # Header row
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            hdr,
            text=f" {icon} ",
            font=("Segoe UI", 10, "bold"),
            fg_color=color,
            corner_radius=4,
            text_color=COLORS["bg"],
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            hdr,
            text=result.name,
            font=("Segoe UI", 12, "bold"),
            text_color=color,
        ).pack(side="left")

        ctk.CTkLabel(
            card,
            text=result.message,
            font=("Segoe UI", 11),
            wraplength=660,
            justify="left",
            text_color=COLORS["fg"],
        ).pack(anchor="w", padx=12, pady=(0, 4 if result.bullet_items else 6))

        if result.bullet_items:
            bullet_frame = ctk.CTkFrame(card, fg_color="transparent")
            bullet_frame.pack(anchor="w", padx=24, pady=(0, 6))
            for item in result.bullet_items:
                ctk.CTkLabel(
                    bullet_frame,
                    text=f"  {item}",
                    font=("Segoe UI", 11),
                    justify="left",
                    text_color=COLORS["fg_muted"],
                    anchor="w",
                ).pack(anchor="w")

        if result.fix_available and result.fix_action:
            fix = ctk.CTkFrame(card, fg_color=COLORS["bg_alt"], corner_radius=6)
            fix.pack(fill="x", padx=12, pady=(0, 10))

            ctk.CTkLabel(
                fix,
                text="Suggested Fix:",
                font=("Segoe UI", 11, "bold"),
                text_color=COLORS["fg_muted"],
            ).pack(anchor="w", padx=8, pady=(6, 2))

            lines = result.fix_action.split("\n")
            has_commands = any(
                line.strip().startswith(("takeown", "icacls")) for line in lines
            )

            if has_commands:
                pending: list[str] = []
                for line in lines:
                    if line.strip().startswith(("takeown", "icacls")):
                        if pending:
                            text = "\n".join(pending).strip()
                            if text:
                                ctk.CTkLabel(
                                    fix,
                                    text=text,
                                    font=("Segoe UI", 11),
                                    wraplength=630,
                                    justify="left",
                                    text_color=COLORS["fg"],
                                ).pack(anchor="w", padx=8, pady=(0, 4))
                            pending = []
                        cmd = ctk.CTkTextbox(
                            fix,
                            height=28,
                            font=("Consolas", 10),
                            wrap="none",
                            fg_color=COLORS["bg"],
                            text_color=COLORS["fg"],
                        )
                        cmd.pack(fill="x", padx=8, pady=2)
                        cmd.insert("1.0", line.strip())
                        cmd.configure(state="disabled")
                    else:
                        pending.append(line)
                if pending:
                    text = "\n".join(pending).strip()
                    if text:
                        ctk.CTkLabel(
                            fix,
                            text=text,
                            font=("Segoe UI", 11),
                            wraplength=630,
                            justify="left",
                            text_color=COLORS["fg"],
                        ).pack(anchor="w", padx=8, pady=(0, 6))
            else:
                ctk.CTkLabel(
                    fix,
                    text=result.fix_action,
                    font=("Segoe UI", 11),
                    wraplength=630,
                    justify="left",
                    text_color=COLORS["fg"],
                ).pack(anchor="w", padx=8, pady=(0, 6))

    def _update_summary(self) -> None:
        """Show count of warnings/errors and make copy button visible."""
        if not self._current_results:
            self._summary_label.configure(text="")
            self._copy_btn.pack_forget()
            return

        counts = {"error": 0, "warning": 0, "info": 0, "ok": 0}
        for r in self._current_results:
            counts[r.status] = counts.get(r.status, 0) + 1

        parts = []
        if counts["error"]:
            parts.append(f"{counts['error']} error{'s' if counts['error'] > 1 else ''}")
        if counts["warning"]:
            parts.append(
                f"{counts['warning']} warning{'s' if counts['warning'] > 1 else ''}"
            )
        if counts["info"]:
            parts.append(f"{counts['info']} info")

        if parts:
            self._summary_label.configure(text=" · ".join(parts))
            self._copy_btn.pack(side="right")
        else:
            self._summary_label.configure(text=f"{counts['ok']} checks passed")
            self._copy_btn.pack(side="right")

    def _copy_results_to_clipboard(self) -> None:
        """Export warnings/errors/info as text to clipboard (skip 'ok' results)."""
        if not self._current_results:
            return

        relevant = [r for r in self._current_results if r.status != "ok"]
        if not relevant:
            # All green, nothing to copy
            self._copy_btn.configure(text="Nothing to copy")
            self.root.after(
                1500, lambda: self._copy_btn.configure(text="Copy to Clipboard")
            )
            return

        lines = [
            f"FromSoftware Troubleshooter {__version__} - {self._game_var.get()}",
            f"OS: {platform.platform()}",
            f"Game folder: {self._game_folder or 'not found'}",
            "=" * 60,
            "",
        ]

        for result in relevant:
            status_icon = STATUS_ICONS.get(result.status, "?")
            lines.append(f"[{status_icon}] {result.name}")
            lines.append(f"    {result.message}")
            if result.bullet_items:
                for item in result.bullet_items:
                    lines.append(f"      • {item}")
            lines.append("")

        text = "\n".join(lines)
        try:
            try:
                # Pyperclip preserves clipboard contents after the app exits on
                # Linux/Wayland and Windows, when its system backend is available.
                pyperclip.copy(text)
            except Exception:
                # Tk is already running for the app and provides a useful fallback
                # when xclip/wl-clipboard is missing or the Windows clipboard is busy.
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.root.update()
            # Flash button to show success
            orig = self._copy_btn.cget("text")
            self._copy_btn.configure(text="✓ Copied!")
            self.root.after(1500, lambda: self._copy_btn.configure(text=orig))
        except Exception:
            # Both clipboard backends can be unavailable in headless or locked sessions.
            self._copy_btn.configure(text="Copy failed - retry")
            self.root.after(
                2500, lambda: self._copy_btn.configure(text="Copy to Clipboard")
            )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = TroubleshooterApp()
    app.run()


if __name__ == "__main__":
    main()
