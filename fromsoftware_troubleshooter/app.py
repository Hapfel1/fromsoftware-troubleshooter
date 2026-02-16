"""Standalone FromSoftware troubleshooter."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

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
    autoscan,
    check_build_id,
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

_SENTINEL = object()


# ---------------------------------------------------------------------------
# Themed yes/no dialog (replaces tkinter.messagebox)
# ---------------------------------------------------------------------------


def _ask_yes_no(parent: ctk.CTk, title: str, message: str) -> bool:
    result: dict[str, bool] = {}

    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.configure(fg_color=COLORS["bg"])

    # Size and center on parent
    w, h = 480, 160
    parent.update_idletasks()
    px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
    py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
    dialog.geometry(f"{w}x{h}+{px}+{py}")
    dialog.grab_set()

    ctk.CTkLabel(
        dialog,
        text=message,
        font=("Segoe UI", 12),
        wraplength=440,
        justify="left",
        text_color=COLORS["fg"],
    ).pack(padx=20, pady=(20, 12), anchor="w")

    btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_row.pack(pady=(0, 16))

    def _yes():
        result["v"] = True
        dialog.destroy()

    def _no():
        result["v"] = False
        dialog.destroy()

    ctk.CTkButton(
        btn_row,
        text="Yes",
        width=100,
        command=_yes,
        fg_color=COLORS["accent"],
        hover_color=COLORS["accent_hover"],
        text_color=COLORS["bg"],
        font=("Segoe UI", 12, "bold"),
    ).pack(side="left", padx=6)

    ctk.CTkButton(
        btn_row,
        text="No",
        width=100,
        command=_no,
        fg_color=COLORS["surface"],
        hover_color=COLORS["surface_alt"],
        text_color=COLORS["fg"],
        font=("Segoe UI", 12),
    ).pack(side="left", padx=6)

    dialog.wait_window()
    return result.get("v", False)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class TroubleshooterApp:
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("FromSoftware Troubleshooter")
        self.root.geometry("740x660")
        self.root.resizable(True, True)
        self.root.configure(fg_color=COLORS["bg"])

        self._game_var = ctk.StringVar(value="Elden Ring")
        self._game_folder: Path | None = None
        self._check_thread: threading.Thread | None = None
        self._result_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._on_game_changed()

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
        game_name = self._game_var.get()
        key = GAME_MANIFEST_KEYS.get(game_name)

        self._game_folder_label.configure(
            text="Scanning...", text_color=COLORS["fg_muted"]
        )
        self.root.update_idletasks()

        game_folder, _ = autoscan(key) if key else (None, None)

        if game_folder:
            self._game_folder = game_folder
            self._game_folder_label.configure(
                text=str(game_folder), text_color=COLORS["fg"]
            )
        else:
            self._game_folder = None
            self._game_folder_label.configure(
                text="Not found automatically", text_color=COLORS["yellow"]
            )
            if _ask_yes_no(
                self.root,
                "Game Not Found",
                f"{game_name} could not be found automatically.\n"
                "Would you like to locate the game folder manually?",
            ):
                self._pick_game_folder()

        self._run_checks()

    def _pick_game_folder(self) -> None:
        folder = filedialog.askdirectory(
            title=f"Select {self._game_var.get()} installation folder",
            parent=self.root,
        )
        if folder:
            self._game_folder = Path(folder)
            self._game_folder_label.configure(
                text=str(self._game_folder), text_color=COLORS["fg"]
            )
            self._run_checks()

    # -------------------------------------------------------------------------

    def _run_checks(self) -> None:
        self._check_thread = None
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

        for widget in self.results_frame.winfo_children():
            widget.destroy()

        self._progress.pack(fill="x", pady=(0, 6))
        self._progress.start()
        self._refresh_btn.configure(state="disabled")

        checker_cls = GAME_OPTIONS.get(self._game_var.get(), EldenRingChecker)
        checker = checker_cls(game_folder=self._game_folder)

        thread = threading.Thread(
            target=self._check_worker,
            args=(checker, self._result_queue),
            daemon=True,
        )
        self._check_thread = thread
        thread.start()
        self.root.after(50, lambda: self._poll_results(thread))

    def _check_worker(self, checker: BaseChecker, q: queue.Queue) -> None:
        def emit(result):
            if isinstance(result, list):
                for r in result:
                    q.put(r)
            else:
                q.put(result)

        emit(check_build_id(checker.MANIFEST_KEY))
        emit(checker._check_game_installation())
        if checker.game_folder and checker.game_folder.exists():
            emit(checker._check_piracy_indicators())
            emit(checker._check_game_executable())
        emit(checker._check_problematic_processes())
        emit(checker._check_vpn_processes())
        emit(checker._check_steam_elevated())
        emit(checker._check_extra())
        q.put(_SENTINEL)

    def _poll_results(self, thread: threading.Thread) -> None:
        if thread is not self._check_thread:
            return
        try:
            while True:
                item = self._result_queue.get_nowait()
                if item is _SENTINEL:
                    self._progress.stop()
                    self._progress.pack_forget()
                    self._refresh_btn.configure(state="normal")
                    return
                self._create_result_widget(item)
        except queue.Empty:
            pass
        self.root.after(50, lambda: self._poll_results(thread))

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
        ).pack(anchor="w", padx=12, pady=(0, 6))

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

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = TroubleshooterApp()
    app.run()


if __name__ == "__main__":
    main()
