"""Standalone FromSoftware troubleshooter — no er_save_manager dependency."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from fromsoftware_troubleshooter.checker import (
    DiagnosticResult,
    DarkSouls1Checker,
    DarkSouls2Checker,
    DarkSouls3Checker,
    EldenRingChecker,
    NightReignChecker,
)

GAME_OPTIONS = {
    "Elden Ring": EldenRingChecker,
    "Elden Ring Nightreign": NightReignChecker,
    "Dark Souls Remastered": DarkSouls1Checker,
    "Dark Souls II: Scholar of the First Sin": DarkSouls2Checker,
    "Dark Souls III": DarkSouls3Checker,
}


class TroubleshooterApp:
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("FromSoftware Troubleshooter")
        self.root.geometry("720x700")
        self.root.resizable(True, True)

        self._game_var = ctk.StringVar(value="Elden Ring")
        self._game_folder: Path | None = None
        self._save_file_path: Path | None = None

        self._build_ui()
        self._run_checks()

    def _build_ui(self):
        main = ctk.CTkFrame(self.root)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            header, text="FromSoftware Troubleshooter",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left")

        ctk.CTkButton(
            header, text="Refresh", command=self._run_checks, width=90,
        ).pack(side="right", padx=(8, 0))

        game_dropdown = ctk.CTkOptionMenu(
            header,
            variable=self._game_var,
            values=list(GAME_OPTIONS.keys()),
            command=lambda _: self._run_checks(),
            width=260,
        )
        game_dropdown.pack(side="right")

        # Path row
        path_frame = ctk.CTkFrame(main, fg_color="transparent")
        path_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkButton(
            path_frame, text="Set Game Folder", command=self._pick_game_folder, width=140,
        ).pack(side="left", padx=(0, 8))

        self._game_folder_label = ctk.CTkLabel(
            path_frame, text="No game folder set", font=("Segoe UI", 11),
            text_color="gray",
        )
        self._game_folder_label.pack(side="left")

        path_frame2 = ctk.CTkFrame(main, fg_color="transparent")
        path_frame2.pack(fill="x", pady=(0, 10))

        ctk.CTkButton(
            path_frame2, text="Set Save File", command=self._pick_save_file, width=140,
        ).pack(side="left", padx=(0, 8))

        self._save_file_label = ctk.CTkLabel(
            path_frame2, text="No save file set", font=("Segoe UI", 11),
            text_color="gray",
        )
        self._save_file_label.pack(side="left")

        # Results
        self.results_frame = ctk.CTkScrollableFrame(main, corner_radius=8)
        self.results_frame.pack(fill="both", expand=True, pady=(0, 10))

        ctk.CTkButton(
            main, text="Close", command=self.root.destroy, width=100,
        ).pack(pady=(5, 0))

    def _pick_game_folder(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Select game installation folder")
        if folder:
            self._game_folder = Path(folder)
            self._game_folder_label.configure(
                text=str(self._game_folder), text_color="white"
            )
            self._run_checks()

    def _pick_save_file(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select save file",
            filetypes=[("Save files", "*.sl2 *.sl2.bak"), ("All files", "*.*")],
        )
        if path:
            self._save_file_path = Path(path)
            self._save_file_label.configure(
                text=str(self._save_file_path), text_color="white"
            )
            self._run_checks()

    def _run_checks(self):
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        loading = ctk.CTkLabel(
            self.results_frame, text="Running diagnostic checks...",
            font=("Segoe UI", 12),
        )
        loading.pack(pady=20)
        self.results_frame.update_idletasks()

        checker_cls = GAME_OPTIONS.get(self._game_var.get(), EldenRingChecker)
        checker = checker_cls(
            game_folder=self._game_folder,
            save_file_path=self._save_file_path,
        )
        results = checker.run_all_checks()
        loading.destroy()

        for result in results:
            self._create_result_widget(result)

    def _create_result_widget(self, result: DiagnosticResult):
        STATUS_ICONS = {"ok": "✅", "warning": "⚠", "error": "✗", "info": "i"}
        STATUS_COLORS = {
            "ok": ("green", "lightgreen"),
            "warning": ("orange", "yellow"),
            "error": ("red", "salmon"),
            "info": ("gray", "lightgray"),
        }

        result_frame = ctk.CTkFrame(self.results_frame, corner_radius=8)
        result_frame.pack(fill="x", padx=5, pady=5)

        header_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=12, pady=(10, 5))

        ctk.CTkLabel(
            header_frame, text=STATUS_ICONS.get(result.status, "i"),
            font=("Segoe UI", 14),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            header_frame, text=result.name,
            font=("Segoe UI", 12, "bold"),
            text_color=STATUS_COLORS.get(result.status, ("gray", "lightgray")),
        ).pack(side="left")

        ctk.CTkLabel(
            result_frame, text=result.message,
            font=("Segoe UI", 11), wraplength=640, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 5))

        if result.fix_available and result.fix_action:
            fix_frame = ctk.CTkFrame(
                result_frame, fg_color=("gray85", "gray25"), corner_radius=6
            )
            fix_frame.pack(fill="x", padx=12, pady=(5, 10))

            ctk.CTkLabel(
                fix_frame, text="Suggested Fix:", font=("Segoe UI", 11, "bold"),
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
                                    fix_frame, text=text, font=("Segoe UI", 11),
                                    wraplength=610, justify="left",
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
                            fix_frame, text=text, font=("Segoe UI", 11),
                            wraplength=610, justify="left",
                        ).pack(anchor="w", padx=8, pady=(0, 5))
            else:
                ctk.CTkLabel(
                    fix_frame, text=result.fix_action, font=("Segoe UI", 11),
                    wraplength=610, justify="left",
                ).pack(anchor="w", padx=8, pady=(0, 5))

    def run(self):
        self.root.mainloop()


def main():
    app = TroubleshooterApp()
    app.run()


if __name__ == "__main__":
    main()