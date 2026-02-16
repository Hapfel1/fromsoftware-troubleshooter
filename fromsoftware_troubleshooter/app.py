"""Standalone FromSoftware troubleshooter."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

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

SAVE_FILE_FILTERS: dict[str, list[tuple[str, str]]] = {
    "Elden Ring": [("ER Save", "ER0000.sl2"), ("All files", "*.*")],
    "Elden Ring Nightreign": [("NR Save", "NR0000.sl2"), ("All files", "*.*")],
    "Dark Souls Remastered": [("DS1 Save", "DRAKS0005.sl2"), ("All files", "*.*")],
    "Dark Souls II: Scholar of the First Sin": [
        ("DS2 Save", "DS2SOFS0000.sl2"),
        ("All files", "*.*"),
    ],
    "Dark Souls III": [("DS3 Save", "DS30000.sl2"), ("All files", "*.*")],
    "Sekiro: Shadows Die Twice": [("Sekiro Save", "S0000.sl2"), ("All files", "*.*")],
    "Armored Core VI: Fires of Rubicon": [
        ("AC6 Save", "AC60000.sl2"),
        ("All files", "*.*"),
    ],
}

_SENTINEL = object()  # signals the worker thread is done


class TroubleshooterApp:
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("FromSoftware Troubleshooter")
        self.root.geometry("740x720")
        self.root.resizable(True, True)

        self._game_var = ctk.StringVar(value="Elden Ring")
        self._game_folder: Path | None = None
        self._save_file_path: Path | None = None
        self._check_thread: threading.Thread | None = None
        self._result_queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._on_game_changed()

    def _build_ui(self) -> None:
        main = ctk.CTkFrame(self.root)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # Header row
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            header,
            text="FromSoftware Troubleshooter",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            header,
            text="Refresh",
            command=self._run_checks,
            width=90,
        )
        self._refresh_btn.pack(side="right", padx=(8, 0))

        ctk.CTkOptionMenu(
            header,
            variable=self._game_var,
            values=list(GAME_OPTIONS.keys()),
            command=lambda _: self._on_game_changed(),
            width=280,
        ).pack(side="right")

        # Game folder row
        folder_row = ctk.CTkFrame(main, fg_color="transparent")
        folder_row.pack(fill="x", pady=(0, 4))

        ctk.CTkButton(
            folder_row,
            text="Set Game Folder",
            command=self._pick_game_folder,
            width=140,
        ).pack(side="left", padx=(0, 8))

        self._game_folder_label = ctk.CTkLabel(
            folder_row,
            text="Scanning...",
            font=("Segoe UI", 11),
            text_color="gray",
            anchor="w",
        )
        self._game_folder_label.pack(side="left", fill="x", expand=True)

        # Save file row
        save_row = ctk.CTkFrame(main, fg_color="transparent")
        save_row.pack(fill="x", pady=(0, 4))

        ctk.CTkButton(
            save_row,
            text="Set Save File",
            command=self._pick_save_file,
            width=140,
        ).pack(side="left", padx=(0, 8))

        self._save_file_label = ctk.CTkLabel(
            save_row,
            text="Scanning...",
            font=("Segoe UI", 11),
            text_color="gray",
            anchor="w",
        )
        self._save_file_label.pack(side="left", fill="x", expand=True)

        # Progress bar (hidden until a check run starts)
        self._progress = ctk.CTkProgressBar(main, mode="indeterminate", height=6)
        self._progress.pack(fill="x", pady=(6, 0))
        self._progress.pack_forget()

        # Results
        self.results_frame = ctk.CTkScrollableFrame(main, corner_radius=8)
        self.results_frame.pack(fill="both", expand=True, pady=(8, 10))

        ctk.CTkButton(
            main,
            text="Close",
            command=self.root.destroy,
            width=100,
        ).pack(pady=(5, 0))

    # -------------------------------------------------------------------------

    def _on_game_changed(self) -> None:
        game_name = self._game_var.get()
        key = GAME_MANIFEST_KEYS.get(game_name)

        self._game_folder_label.configure(text="Scanning...", text_color="gray")
        self._save_file_label.configure(text="Scanning...", text_color="gray")
        self.root.update_idletasks()

        game_folder, save_file = autoscan(key) if key else (None, None)

        if game_folder:
            self._game_folder = game_folder
            self._game_folder_label.configure(text=str(game_folder), text_color="white")
        else:
            self._game_folder = None
            self._game_folder_label.configure(
                text="Not found automatically", text_color="orange"
            )
            self._prompt_manual_game_folder(game_name)

        if save_file:
            self._save_file_path = save_file
            self._save_file_label.configure(text=str(save_file), text_color="white")
        else:
            self._save_file_path = None
            self._save_file_label.configure(
                text="Not found — set manually if needed", text_color="gray"
            )

        self._run_checks()

    def _prompt_manual_game_folder(self, game_name: str) -> None:
        answer = messagebox.askyesno(
            "Game Not Found",
            f"{game_name} could not be found automatically.\n\n"
            "Would you like to locate the game folder manually?",
            parent=self.root,
        )
        if answer:
            self._pick_game_folder()

    def _pick_game_folder(self) -> None:
        folder = filedialog.askdirectory(
            title=f"Select {self._game_var.get()} installation folder",
            parent=self.root,
        )
        if folder:
            self._game_folder = Path(folder)
            self._game_folder_label.configure(
                text=str(self._game_folder), text_color="white"
            )
            self._run_checks()

    def _pick_save_file(self) -> None:
        game_name = self._game_var.get()
        filetypes = SAVE_FILE_FILTERS.get(
            game_name, [("Save files", "*.sl2"), ("All files", "*.*")]
        )
        path = filedialog.askopenfilename(
            title=f"Select {game_name} save file",
            filetypes=filetypes,
            parent=self.root,
        )
        if path:
            self._save_file_path = Path(path)
            self._save_file_label.configure(
                text=str(self._save_file_path), text_color="white"
            )
            self._run_checks()

    # -------------------------------------------------------------------------

    def _run_checks(self) -> None:
        # Cancel any in-progress run
        self._check_thread = None
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

        for widget in self.results_frame.winfo_children():
            widget.destroy()

        self._progress.pack(fill="x", pady=(6, 0))
        self._progress.start()
        self._refresh_btn.configure(state="disabled")

        checker_cls = GAME_OPTIONS.get(self._game_var.get(), EldenRingChecker)
        checker = checker_cls(
            game_folder=self._game_folder,
            save_file_path=self._save_file_path,
        )

        # Snapshot which thread this is so stale threads don't write to UI
        thread = threading.Thread(
            target=self._check_worker,
            args=(checker, self._result_queue),
            daemon=True,
        )
        self._check_thread = thread
        thread.start()
        self.root.after(50, lambda: self._poll_results(thread))

    def _check_worker(self, checker: BaseChecker, q: queue.Queue) -> None:
        """Run checks one by one, pushing each result to the queue immediately."""
        manifest_key = checker.MANIFEST_KEY

        # Order mirrors run_all_checks but yields each result as it finishes
        checks = [
            lambda: check_build_id(manifest_key),
            lambda: checker._check_game_installation(),
        ]
        if checker.game_folder and checker.game_folder.exists():
            checks += [
                lambda: checker._check_piracy_indicators(),  # returns list
                lambda: checker._check_game_executable(),
            ]
        checks += [
            lambda: checker._check_problematic_processes(),  # returns list
            lambda: checker._check_vpn_processes(),  # returns list
            lambda: checker._check_steam_elevated(),
        ]
        if checker.save_file_path:
            checks.append(lambda: checker._check_save_file_health())  # returns list
        checks.append(lambda: checker._check_extra())  # returns list

        for check in checks:
            result = check()
            if isinstance(result, list):
                for r in result:
                    q.put(r)
            else:
                q.put(result)

        q.put(_SENTINEL)

    def _poll_results(self, thread: threading.Thread) -> None:
        """Poll the queue and render results as they arrive."""
        if thread is not self._check_thread:
            return  # stale thread, discard

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
        STATUS_ICONS = {"ok": "OK", "warning": "!", "error": "X", "info": "i"}
        STATUS_COLORS: dict[str, tuple[str, str]] = {
            "ok": ("#2d7a2d", "#4caf50"),
            "warning": ("#b36a00", "#ffb300"),
            "error": ("#8b0000", "#f44336"),
            "info": ("#4a4a4a", "#9e9e9e"),
        }

        result_frame = ctk.CTkFrame(self.results_frame, corner_radius=8)
        result_frame.pack(fill="x", padx=5, pady=5)

        header_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=(10, 5))

        color = STATUS_COLORS.get(result.status, STATUS_COLORS["info"])

        badge = ctk.CTkLabel(
            header_frame,
            text=f" {STATUS_ICONS.get(result.status, 'i')} ",
            font=("Segoe UI", 11, "bold"),
            fg_color=color,
            corner_radius=4,
            text_color="white",
        )
        badge.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            header_frame,
            text=result.name,
            font=("Segoe UI", 12, "bold"),
            text_color=color[1],
        ).pack(side="left")

        ctk.CTkLabel(
            result_frame,
            text=result.message,
            font=("Segoe UI", 11),
            wraplength=660,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 5))

        if result.fix_available and result.fix_action:
            fix_frame = ctk.CTkFrame(
                result_frame, fg_color=("gray85", "gray25"), corner_radius=6
            )
            fix_frame.pack(fill="x", padx=12, pady=(5, 10))

            ctk.CTkLabel(
                fix_frame,
                text="Suggested Fix:",
                font=("Segoe UI", 11, "bold"),
            ).pack(anchor="w", padx=8, pady=(5, 2))

            lines = result.fix_action.split("\n")
            has_commands = any(
                line.strip().startswith(("takeown", "icacls")) for line in lines
            )

            if has_commands:
                current_text: list[str] = []
                for line in lines:
                    if line.strip().startswith(("takeown", "icacls")):
                        if current_text:
                            text = "\n".join(current_text).strip()
                            if text:
                                ctk.CTkLabel(
                                    fix_frame,
                                    text=text,
                                    font=("Segoe UI", 11),
                                    wraplength=630,
                                    justify="left",
                                ).pack(anchor="w", padx=8, pady=(0, 5))
                            current_text = []
                        cmd_box = ctk.CTkTextbox(
                            fix_frame, height=30, font=("Consolas", 10), wrap="none"
                        )
                        cmd_box.pack(fill="x", padx=8, pady=(2, 2))
                        cmd_box.insert("1.0", line.strip())
                        cmd_box.configure(state="disabled")
                    else:
                        current_text.append(line)
                if current_text:
                    text = "\n".join(current_text).strip()
                    if text:
                        ctk.CTkLabel(
                            fix_frame,
                            text=text,
                            font=("Segoe UI", 11),
                            wraplength=630,
                            justify="left",
                        ).pack(anchor="w", padx=8, pady=(0, 5))
            else:
                ctk.CTkLabel(
                    fix_frame,
                    text=result.fix_action,
                    font=("Segoe UI", 11),
                    wraplength=630,
                    justify="left",
                ).pack(anchor="w", padx=8, pady=(0, 5))

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = TroubleshooterApp()
    app.run()


if __name__ == "__main__":
    main()
