"""Standalone checker."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiagnosticResult:
    name: str
    status: str  # 'ok', 'warning', 'error', 'info'
    message: str
    fix_available: bool = False
    fix_action: str = ""
    bullet_items: list[str] = None

    def __post_init__(self):
        if self.bullet_items is None:
            self.bullet_items = []


# ---------------------------------------------------------------------------
# Remote file size manifest
# ---------------------------------------------------------------------------

MANIFEST_URL = (
    "https://raw.githubusercontent.com/Hapfel1/fromsoftware-troubleshooter"
    "/master/game_file_sizes.json"
)
_MANIFEST_CACHE: dict | None = None


_DEBUG = os.environ.get("FST_DEBUG") == "1"


def _dbg(msg: str) -> None:
    if _DEBUG:
        print(f"[FST] {msg}")


def _load_manifest() -> dict:
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None:
        _dbg("manifest: using cache")
        return _MANIFEST_CACHE
    _dbg(f"manifest: fetching from {MANIFEST_URL}")
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=3) as resp:
            _MANIFEST_CACHE = json.loads(resp.read().decode())
            _dbg(f"manifest: loaded from remote, keys={list(_MANIFEST_CACHE.keys())}")
            return _MANIFEST_CACHE
    except Exception as e:
        _dbg(f"manifest: remote fetch failed ({e}), trying local")
    # Local fallback: check several likely locations
    candidates = [
        Path(__file__).with_name("game_file_sizes.json"),       # alongside checker.py
        Path(__file__).parent.parent / "game_file_sizes.json",  # project root (dev layout)
        Path.cwd() / "game_file_sizes.json",                    # working directory
    ]
    for candidate in candidates:
        _dbg(f"manifest: checking {candidate} — exists={candidate.exists()}")
        if candidate.exists():
            try:
                _MANIFEST_CACHE = json.loads(candidate.read_text())
                _dbg(f"manifest: loaded from {candidate}, keys={list(_MANIFEST_CACHE.keys())}")
                return _MANIFEST_CACHE
            except Exception as e:
                _dbg(f"manifest: failed to parse {candidate} ({e})")
    _dbg("manifest: all sources failed, returning empty dict")
    return {}


def _get_size_entry(game_key: str, file_key: str) -> dict | None:
    return _load_manifest().get(game_key, {}).get(file_key)


# ---------------------------------------------------------------------------
# Build ID / update check
# ---------------------------------------------------------------------------

_build_id_cache: dict[str, int | None] = {}


def _read_local_build_id(app_id: str) -> int | None:
    """Read the installed build ID from the local Steam ACF manifest."""
    if app_id in _build_id_cache:
        return _build_id_cache[app_id]
    for root in _get_steam_library_folders():
        acf = root / f"appmanifest_{app_id}.acf"
        if not acf.exists():
            continue
        try:
            text = acf.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'"buildid"\s+"([^"]+)"', text, re.IGNORECASE)
            if m:
                _build_id_cache[app_id] = int(m.group(1))
                return _build_id_cache[app_id]
        except Exception:
            pass
    _build_id_cache[app_id] = None
    return None


def check_build_id(manifest_key: str) -> DiagnosticResult:
    """
    Compare the stored build ID in the manifest against the locally installed build ID
    read from the Steam ACF manifest. Warns if the game has been updated since the
    file size reference was recorded.
    """
    app_id = _APP_IDS.get(manifest_key)
    stored = _load_manifest().get(manifest_key, {}).get("build_id", 0)

    if not app_id:
        return DiagnosticResult(
            name="Game Version Check", status="info",
            message="No app ID configured for this game",
        )

    _dbg(f"build_id check: manifest_key={manifest_key} stored={stored}")

    if stored == 0:
        return DiagnosticResult(
            name="Game Version Check", status="info",
            message="No reference build ID recorded — size checks may not reflect the latest patch",
        )

    current = _read_local_build_id(app_id)
    _dbg(f"build_id check: local ACF build_id={current}")
    if current is None:
        return DiagnosticResult(
            name="Game Version Check", status="info",
            message="Game not found in Steam libraries — cannot verify build ID",
        )

    if current != stored:
        return DiagnosticResult(
            name="Game Version Check", status="warning",
            message=(
                f"Game has been updated since file sizes were recorded "
                f"(recorded build {stored}, installed build {current}). "
                "Size checks may be inaccurate."
            ),
        )

    return DiagnosticResult(
        name="Game Version Check", status="ok",
        message=f"Game is on the expected build ({current})",
    )


def _check_file_size(path: Path, game_key: str, file_key: str) -> str:
    """
    Returns 'ok', 'warning', or 'unknown'.
    'warning' means file exists but size is outside the expected range.
    """
    entry = _get_size_entry(game_key, file_key)
    size = path.stat().st_size
    if not entry:
        return "unknown"
    if entry["min"] <= size <= entry["max"]:
        return "ok"
    return "warning"


def _format_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    return f"{size_bytes:,} bytes ({mb:.1f} MB)"


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _is_windows() -> bool:
    return platform.system() == "Windows"


def _get_running_process_names() -> set[str]:
    """Return a set of lowercase running process names, cross-platform."""
    names: set[str] = set()
    if _is_windows():
        try:
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"], text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in out.splitlines():
                parts = line.strip().strip('"').split('","')
                if parts:
                    names.add(parts[0].lower())
        except Exception:
            pass
    else:
        # Linux: read /proc/*/comm (process name, max 15 chars) and /proc/*/exe
        proc = Path("/proc")
        for pid_dir in proc.iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                names.add((pid_dir / "comm").read_text().strip().lower())
            except OSError:
                pass
            try:
                exe = (pid_dir / "exe").resolve()
                names.add(exe.name.lower())
            except OSError:
                pass
    return names


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _is_flatpak_steam() -> bool:
    if not _is_linux():
        return False
    return (
        Path.home()
        / ".var" / "app" / "com.valvesoftware.Steam"
        / ".local" / "share" / "Steam"
    ).exists()


def _get_steam_library_folders() -> list[Path]:
    """Return all Steam steamapps directories on this machine."""
    libraries: list[Path] = []

    if _is_windows():
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Valve\Steam",
            )
            steam_path = Path(winreg.QueryValueEx(key, "InstallPath")[0])
            libraries.append(steam_path / "steamapps")
        except Exception:
            pass
        for drive in "CDEF":
            for stem in (
                Path(f"{drive}:/Program Files (x86)/Steam/steamapps"),
                Path(f"{drive}:/Steam/steamapps"),
            ):
                if stem.exists():
                    libraries.append(stem)

    elif _is_linux():
        for candidate in (
            Path.home() / ".local" / "share" / "Steam" / "steamapps",
            Path.home() / ".steam" / "steam" / "steamapps",
            Path.home() / ".var" / "app" / "com.valvesoftware.Steam"
            / ".local" / "share" / "Steam" / "steamapps",
        ):
            if candidate.exists():
                libraries.append(candidate)

    elif platform.system() == "Darwin":
        candidate = (
            Path.home() / "Library" / "Application Support" / "Steam" / "steamapps"
        )
        if candidate.exists():
            libraries.append(candidate)

    # Expand via libraryfolders.vdf
    expanded = list(libraries)
    for root in libraries:
        for vdf in (
            root / "libraryfolders.vdf",
            root.parent / "config" / "libraryfolders.vdf",
        ):
            if vdf.exists():
                try:
                    text = vdf.read_text(encoding="utf-8", errors="ignore")
                    for path_str in re.findall(r'"path"\s+"([^"]+)"', text):
                        extra = Path(path_str) / "steamapps"
                        if extra.exists() and extra not in expanded:
                            expanded.append(extra)
                except Exception:
                    pass
                break

    # Deduplicate, resolve symlinks
    seen: set[Path] = set()
    result: list[Path] = []
    for p in expanded:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp not in seen:
            seen.add(rp)
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Game metadata
# ---------------------------------------------------------------------------

_APP_IDS: dict[str, str] = {
    "elden_ring":            "1245620",
    "nightreign":            "2622380",
    "dark_souls_remastered": "570940",
    "dark_souls_2":          "335300",
    "dark_souls_3":          "374320",
    "sekiro":                "814380",
    "armored_core_6":        "1888160",
}

# Subfolder inside AppData/Roaming (Windows) or Wine prefix equivalent (Linux)
_SAVE_ROAMING_SUBPATHS: dict[str, str] = {
    "elden_ring":            "EldenRing",
    "nightreign":            "NightReign",
    "dark_souls_remastered": "DarkSoulsRemastered",
    "dark_souls_2":          "DarkSoulsII/SOFTS",
    "dark_souls_3":          "DarkSoulsIII",
    "sekiro":                "Sekiro",
    "armored_core_6":        "ArmoredCore6",
}

_SAVE_FILENAMES: dict[str, str] = {
    "elden_ring":            "ER0000.sl2",
    "nightreign":            "NR0000.sl2",
    "dark_souls_remastered": "DRAKS0005.sl2",
    "dark_souls_2":          "DS2SOFS0000.sl2",
    "dark_souls_3":          "DS30000.sl2",
    "sekiro":                "S0000.sl2",
    "armored_core_6":        "AC60000.sl2",
}

_BACKUP_EXTENSIONS = {".bak", ".backup", ".backups"}


def find_game_folder(manifest_key: str) -> Path | None:
    """Locate game installation folder via Steam ACF manifests."""
    app_id = _APP_IDS.get(manifest_key)
    if not app_id:
        return None
    for root in _get_steam_library_folders():
        acf = root / f"appmanifest_{app_id}.acf"
        if not acf.exists():
            continue
        try:
            text = acf.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'"installdir"\s+"([^"]+)"', text, re.IGNORECASE)
            if m:
                candidate = root / "common" / m.group(1)
                if candidate.exists():
                    return candidate
        except Exception:
            pass
    return None


def find_save_file(manifest_key: str) -> Path | None:
    """
    Locate the primary save file for a game.
    Returns the most recently modified match, ignoring backups.
    """
    filename = _SAVE_FILENAMES.get(manifest_key)
    app_id = _APP_IDS.get(manifest_key)
    subpath = _SAVE_ROAMING_SUBPATHS.get(manifest_key, "")
    if not filename or not app_id:
        return None

    candidates: list[Path] = []

    if _is_windows():
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        base = appdata / subpath
        if base.exists():
            candidates.extend(base.rglob(filename))

    elif _is_linux():
        wine_roaming = (
            Path("pfx") / "drive_c" / "users" / "steamuser"
            / "AppData" / "Roaming" / subpath
        )
        for root in _get_steam_library_folders():
            compat = root / "compatdata" / app_id
            if compat.exists():
                roaming = compat / wine_roaming
                if roaming.exists():
                    candidates.extend(roaming.rglob(filename))
            # Steam userdata (cloud sync)
            userdata = root.parent / "userdata"
            if userdata.exists():
                for user_dir in userdata.iterdir():
                    if not user_dir.is_dir():
                        continue
                    remote = user_dir / app_id / "remote" / filename
                    if remote.exists():
                        candidates.append(remote)

    elif platform.system() == "Darwin":
        app_support = Path.home() / "Library" / "Application Support" / subpath
        if app_support.exists():
            candidates.extend(app_support.rglob(filename))

    candidates = [
        p for p in candidates
        if p.is_file() and p.suffix not in _BACKUP_EXTENSIONS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def autoscan(manifest_key: str) -> tuple[Path | None, Path | None]:
    """Return (game_folder, save_file_path) for the given game."""
    return find_game_folder(manifest_key), find_save_file(manifest_key)


# ---------------------------------------------------------------------------
# Process lists
# ---------------------------------------------------------------------------

# High confidence — known to cause crashes or EAC issues
PROBLEMATIC_PROCESSES = [
    # Windows
    "vgtray.exe", "RTSS.exe", "RTSSHooksLoader64.exe",
    "SystemExplorer.exe", "MSIAfterburner.exe", "SignalRgb.exe",
    "ProcessLasso.exe",
]

# Low confidence — unlikely to cause issues but worth knowing
INFORMATIONAL_PROCESSES = [
    # Windows
    "Discord.exe", "Overwolf.exe", "Medal.exe", "GeForceExperience.exe",
    "XboxGameBar.exe", "GameBarFTServer.exe",
    "EpicGamesLauncher.exe", "GalaxyClient.exe",
    # Linux
    "discord", "vesktop", "armcord",
]

VPN_PROCESSES = [
    # Windows
    "NordVPN.exe", "nordvpn-service.exe", "expressvpn.exe", "expressvpnd.exe",
    "surfshark.exe", "SurfsharkService.exe", "protonvpn.exe", "ProtonVPN.exe",
    "CyberGhost.exe", "CG7Service.exe", "pia-client.exe", "pia-service.exe",
    "windscribe.exe", "windscribeservice.exe", "TunnelBear.exe",
    "TunnelBearService.exe", "hsscp.exe", "IPVanish.exe", "AtlasVPN.exe",
    "Cloudflare WARP.exe", "warp-svc.exe", "hamachi-2.exe", "hamachi-2-ui.exe",
    "Radmin VPN.exe", "RvpnService.exe",
    # Linux
    "nordvpnd", "nordvpn", "expressvpn", "protonvpn",
    "mullvad", "mullvad-vpn", "mullvad-daemon", "mullvad-gui",
    "windscribe", "windscribed", "openvpn", "openconnect", "wg-quick",
]


# ---------------------------------------------------------------------------
# Base checker
# ---------------------------------------------------------------------------

class BaseChecker:
    GAME_NAME: str = ""
    MANIFEST_KEY: str = ""
    EXE_NAME: str = ""
    SAVE_FILE_NAME: str = ""
    # Set to "Game" for games with a Game/ subfolder, "" for flat installs
    GAME_SUBFOLDER: str = "Game"
    PIRACY_FOLDERS: list[str] = []
    PIRACY_FILES: list[str] = []

    def __init__(
        self,
        game_folder: Path | None = None,
        save_file_path: Path | None = None,
    ):
        self.game_folder = Path(game_folder) if game_folder else None
        self.save_file_path = Path(save_file_path) if save_file_path else None

    @property
    def _game_dir(self) -> Path | None:
        """Directory that contains the exe and game files."""
        if not self.game_folder:
            return None
        if self.GAME_SUBFOLDER:
            return self.game_folder / self.GAME_SUBFOLDER
        return self.game_folder

    def run_all_checks(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        results.append(check_build_id(self.MANIFEST_KEY))
        results.append(self._check_game_installation())
        if self.game_folder and self.game_folder.exists():
            results.extend(self._check_piracy_indicators())
            results.append(self._check_game_executable())
        results.extend(self._check_problematic_processes())
        results.extend(self._check_vpn_processes())
        results.append(self._check_steam_elevated())
        if self.save_file_path:
            results.extend(self._check_save_file_health())
        results.extend(self._check_extra())
        return results

    def _check_extra(self) -> list[DiagnosticResult]:
        return []

    def _check_game_installation(self) -> DiagnosticResult:
        if not self.game_folder:
            return DiagnosticResult(
                name="Game Installation", status="warning",
                message="Game folder not specified",
            )
        if not self.game_folder.exists():
            return DiagnosticResult(
                name="Game Installation", status="error",
                message=f"Game folder not found: {self.game_folder}",
            )
        return DiagnosticResult(
            name="Game Installation", status="ok",
            message=f"Game folder found: {self.game_folder}",
        )

    def _check_game_executable(self) -> DiagnosticResult:
        game_dir = self._game_dir
        if not game_dir or not self.EXE_NAME:
            return DiagnosticResult(
                name="Game Executable", status="info", message="Game folder not set"
            )
        exe_path = game_dir / self.EXE_NAME
        if not exe_path.exists():
            return DiagnosticResult(
                name="Game Executable", status="error",
                message=f"{self.EXE_NAME} not found in {game_dir}",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        actual_size = exe_path.stat().st_size
        size_status = _check_file_size(exe_path, self.MANIFEST_KEY, "exe")
        entry = _get_size_entry(self.MANIFEST_KEY, "exe")

        if size_status == "ok":
            return DiagnosticResult(
                name="Game Executable", status="ok",
                message=f"{self.EXE_NAME} found — {_format_size(actual_size)}",
            )
        elif size_status == "warning":
            expected = _format_size(entry["exact"]) if entry else "unknown"
            return DiagnosticResult(
                name="Game Executable", status="warning",
                message=(
                    f"{self.EXE_NAME} size is unexpected.\n"
                    f"Found: {_format_size(actual_size)}\n"
                    f"Expected: {expected}"
                ),
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        return DiagnosticResult(
            name="Game Executable", status="info",
            message=f"{self.EXE_NAME} found — {_format_size(actual_size)} (no reference size available)",
        )

    def _check_piracy_indicators(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        game_dir = self._game_dir
        if not game_dir or not game_dir.exists():
            return results

        found_folders = [f for f in self.PIRACY_FOLDERS if (game_dir / f).exists()]
        if found_folders:
            results.append(DiagnosticResult(
                name="Unsupported Folders Detected", status="warning",
                message="Found unsupported folders in the game directory:",
                bullet_items=list(found_folders),
            ))

        found_files: list[str] = []
        for f in self.PIRACY_FILES:
            if (game_dir / f).exists():
                found_files.append(f)

        steam_api = game_dir / "steam_api64.dll"
        if steam_api.exists():
            size_status = _check_file_size(steam_api, self.MANIFEST_KEY, "steam_api64.dll")
            if size_status == "warning":
                actual = steam_api.stat().st_size
                found_files.append(f"steam_api64.dll (unexpected size: {actual:,} bytes)")
        else:
            results.append(DiagnosticResult(
                name="Critical File Missing", status="error",
                message="steam_api64.dll is missing from game folder",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            ))

        if found_files:
            results.append(DiagnosticResult(
                name="Unsupported/Damaged Files Detected", status="error",
                message="Found unsupported or modified files in the game directory:",
                bullet_items=list(found_files),
                fix_available=True,
                fix_action="Delete the unsupported files and verify game integrity via Steam.",
            ))
        else:
            results.append(DiagnosticResult(
                name="Game Integrity", status="ok",
                message="No integrity issues detected",
            ))
        return results

    def _check_regulation_bin(self) -> DiagnosticResult:
        game_dir = self._game_dir
        if not game_dir:
            return DiagnosticResult(
                name="Regulation File", status="info", message="Game folder not set"
            )
        regulation = game_dir / "regulation.bin"
        if not regulation.exists():
            return DiagnosticResult(
                name="Critical File Missing", status="error",
                message="regulation.bin is missing from game folder",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        actual_size = regulation.stat().st_size
        size_status = _check_file_size(regulation, self.MANIFEST_KEY, "regulation.bin")
        entry = _get_size_entry(self.MANIFEST_KEY, "regulation.bin")

        if size_status == "ok":
            return DiagnosticResult(
                name="Regulation File", status="ok",
                message=f"regulation.bin is valid — {_format_size(actual_size)}",
            )
        elif size_status == "warning":
            expected = _format_size(entry["exact"]) if entry else "unknown"
            return DiagnosticResult(
                name="Regulation File", status="warning",
                message=(
                    f"regulation.bin size is unexpected. May indicate modified game files.\n"
                    f"Found: {_format_size(actual_size)}\n"
                    f"Expected: {expected}"
                ),
                fix_available=True,
                fix_action="Delete the file and verify game integrity via Steam.",
            )
        return DiagnosticResult(
            name="Regulation File", status="info",
            message=f"regulation.bin found — {_format_size(actual_size)} (no reference size available)",
        )

    def _check_problematic_processes(self) -> list[DiagnosticResult]:
        try:
            running_names = _get_running_process_names()
        except Exception as e:
            return [DiagnosticResult(
                name="Process Check", status="warning",
                message=f"Could not check processes: {e}",
            )]

        running = [p for p in PROBLEMATIC_PROCESSES if p.lower().replace(".exe", "") in
                   {n.replace(".exe", "") for n in running_names}]
        info_running = [p for p in INFORMATIONAL_PROCESSES if p.lower().replace(".exe", "") in
                        {n.replace(".exe", "") for n in running_names}]

        process_lasso_scheduled = False
        if _is_windows():
            try:
                schtasks = subprocess.check_output(
                    ["schtasks", "/query", "/fo", "LIST", "/v"], text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if "processlasso" in schtasks.lower():
                    process_lasso_scheduled = True
            except Exception:
                pass

        results: list[DiagnosticResult] = []

        if running:
            fix = ("Close these apps before playing, and disable them in Task Manager > Startup tab."
                   if _is_windows() else
                   "Close these apps before launching the game.")
            results.append(DiagnosticResult(
                name="Problematic Processes Running", status="warning",
                message="The following processes can cause crashes or connection issues:",
                bullet_items=list(running),
                fix_available=True,
                fix_action=fix,
            ))

        if any("processlasso" in p.lower() for p in running) or process_lasso_scheduled:
            results.append(DiagnosticResult(
                name="Process Lasso Detected", status="error",
                message="Process Lasso can cause flashbang crashes on launch.",
                fix_available=True,
                fix_action="1. Close Process Lasso if running\n2. Disable in Task Manager > Startup tab\n3. Remove from Task Scheduler > Task Scheduler Library",
            ))

        if info_running:
            results.append(DiagnosticResult(
                name="Low-Priority Processes", status="info",
                message="These are running but very unlikely to cause issues:",
                bullet_items=list(info_running),
            ))

        if not running and not process_lasso_scheduled:
            results.append(DiagnosticResult(
                name="Process Check", status="ok",
                message="No problematic processes detected",
            ))

        return results

    def _check_vpn_processes(self) -> list[DiagnosticResult]:
        try:
            running_names = _get_running_process_names()
        except Exception as e:
            return [DiagnosticResult(
                name="VPN Check", status="warning",
                message=f"Could not check for VPN processes: {e}",
            )]

        seen: set[str] = set()
        running_vpns: list[str] = []
        # Strip .exe and normalise to lowercase for matching
        normalised_running = {n.replace(".exe", "").lower() for n in running_names}
        for proc in VPN_PROCESSES:
            proc_norm = proc.lower().replace(".exe", "")
            base = proc_norm.split("-")[0]
            if base in seen:
                continue
            # Match exact name or prefix (catches mullvad-daemon matching "mullvad" entry)
            matched = proc_norm in normalised_running or any(
                n == proc_norm or n.startswith(proc_norm + "-") or proc_norm.startswith(n + "-")
                for n in normalised_running
            )
            if matched:
                seen.add(base)
                running_vpns.append(proc_norm)

        if running_vpns:
            return [DiagnosticResult(
                name="VPN Detected", status="warning",
                message="Active VPN client(s) detected — may cause multiplayer issues:",
                bullet_items=running_vpns,
                fix_available=True,
                fix_action="Disable or exit your VPN before playing online.",
            )]
        return [DiagnosticResult(
            name="VPN Check", status="ok", message="No VPN clients detected",
        )]

    def _check_steam_elevated(self) -> DiagnosticResult:
        if not _is_windows():
            return DiagnosticResult(
                name="Steam Elevation Check", status="info",
                message="Steam elevation check only available on Windows",
            )
        ps_script = """
            Add-Type -TypeDefinition @"
            using System; using System.Runtime.InteropServices; using System.Diagnostics;
            public class ProcessChecker {
                [DllImport("advapi32.dll", SetLastError=true)]
                public static extern bool OpenProcessToken(IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);
                [DllImport("advapi32.dll", SetLastError=true)]
                public static extern bool GetTokenInformation(IntPtr TokenHandle, int TokenInformationClass, IntPtr TokenInformation, uint TokenInformationLength, out uint ReturnLength);
                [DllImport("kernel32.dll", SetLastError=true)]
                public static extern bool CloseHandle(IntPtr hObject);
                public static int CheckProcessElevation(int processId) {
                    IntPtr tokenHandle = IntPtr.Zero;
                    try {
                        Process process = Process.GetProcessById(processId);
                        if (OpenProcessToken(process.Handle, 0x0008, out tokenHandle)) {
                            uint returnLength; IntPtr elevationResult = Marshal.AllocHGlobal(4);
                            try { if (GetTokenInformation(tokenHandle, 20, elevationResult, 4, out returnLength)) { return Marshal.ReadInt32(elevationResult) != 0 ? 1 : 0; } }
                            finally { Marshal.FreeHGlobal(elevationResult); }
                        }
                        return 0;
                    } catch (System.ComponentModel.Win32Exception ex) { if (ex.NativeErrorCode == 5) { return 1; } return -1;
                    } catch (UnauthorizedAccessException) { return 1;
                    } catch { return -1;
                    } finally { if (tokenHandle != IntPtr.Zero) { CloseHandle(tokenHandle); } }
                }
            }
"@
            $procs = Get-Process -Name "steam" -ErrorAction SilentlyContinue
            if (-not $procs) { Write-Output "not_running"; exit 1 }
            $elevated = $false
            foreach ($p in $procs) { try { if ([ProcessChecker]::CheckProcessElevation($p.Id) -eq 1) { $elevated = $true; break } } catch {} }
            if ($elevated) { Write-Output "elevated" } else { Write-Output "normal" }
        """
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=5,
            )
            output = ""
            for line in reversed(result.stdout.strip().split("\n")):
                stripped = line.strip().lower()
                if stripped and not stripped.startswith("debug:"):
                    output = stripped
                    break
            if output == "not_running":
                return DiagnosticResult(
                    name="Steam Elevation Check", status="info",
                    message="Steam is not currently running",
                )
            elif output == "elevated":
                appdata_path = Path(os.environ.get("APPDATA", "")) / self.GAME_NAME
                fix_message = (
                    "Steam is running with administrator privileges.\n\n"
                    "1. Exit Steam, right-click steam.exe > Properties > Compatibility\n"
                    "   Uncheck 'Run this program as an administrator'\n\n"
                    "2. Take Ownership (PowerShell as Admin):\n\n"
                    f'takeown /F "{self.game_folder}" /R /D Y\n'
                    f'icacls "{self.game_folder}" /grant %USERNAME%:F /T\n\n'
                    f'takeown /F "{appdata_path}" /R /D Y\n'
                    f'icacls "{appdata_path}" /grant %USERNAME%:F /T'
                )
                return DiagnosticResult(
                    name="Steam Running as Administrator", status="error",
                    message="Steam is running with elevated privileges. This can cause save file permission issues.",
                    fix_available=True, fix_action=fix_message,
                )
            elif output == "normal":
                return DiagnosticResult(
                    name="Steam Elevation Check", status="ok",
                    message="Steam is running with normal privileges",
                )
            return DiagnosticResult(
                name="Steam Elevation Check", status="warning",
                message="Could not determine if Steam is elevated",
            )
        except subprocess.TimeoutExpired:
            return DiagnosticResult(
                name="Steam Elevation Check", status="warning",
                message="Steam elevation check timed out",
            )
        except Exception as e:
            return DiagnosticResult(
                name="Steam Elevation Check", status="warning",
                message=f"Could not check Steam elevation: {e}",
            )

    def _check_save_file_health(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        if not self.save_file_path or not self.save_file_path.exists():
            return [DiagnosticResult(
                name="Save File",
                status="error" if self.save_file_path else "info",
                message=f"Save file not found: {self.save_file_path}"
                if self.save_file_path else "No save file loaded",
            )]
        if not os.access(self.save_file_path, os.R_OK):
            results.append(DiagnosticResult(
                name="Save File Permissions", status="error",
                message="Cannot read save file — check file permissions",
                fix_available=True,
                fix_action="Run as administrator or check file permissions",
            ))
        else:
            results.append(DiagnosticResult(
                name="Save File Permissions", status="ok",
                message="Save file is readable",
            ))
        file_size = self.save_file_path.stat().st_size
        if file_size < 1000:
            results.append(DiagnosticResult(
                name="Save File Size", status="error",
                message=f"Save file suspiciously small ({file_size:,} bytes) — may be corrupted",
            ))
        else:
            results.append(DiagnosticResult(
                name="Save File Size", status="ok",
                message=f"Save file size: {_format_size(file_size)}",
            ))
        if _is_windows():
            try:
                import shutil
                _, _, free = shutil.disk_usage(self.save_file_path.parent)
                free_gb = free // (1024 ** 3)
                results.append(DiagnosticResult(
                    name="Disk Space",
                    status="warning" if free_gb < 1 else "ok",
                    message=f"{'Low disk space' if free_gb < 1 else 'Sufficient disk space'}: {free_gb} GB free",
                    fix_available=free_gb < 1,
                    fix_action="Free up disk space for save backups" if free_gb < 1 else "",
                ))
            except Exception:
                pass
        return results


# ---------------------------------------------------------------------------
# Game subclasses
# ---------------------------------------------------------------------------

class EldenRingChecker(BaseChecker):
    GAME_NAME = "Elden Ring"
    MANIFEST_KEY = "elden_ring"
    EXE_NAME = "eldenring.exe"
    SAVE_FILE_NAME = "ER0000.sl2"
    GAME_SUBFOLDER = "Game"
    PIRACY_FOLDERS = ["_CommonRedist", "AdvGuide", "ArtbookOST"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll", "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
        return results


class NightReignChecker(BaseChecker):
    GAME_NAME = "Elden Ring Nightreign"
    MANIFEST_KEY = "nightreign"
    EXE_NAME = "nightreign.exe"
    SAVE_FILE_NAME = "NR0000.sl2"
    GAME_SUBFOLDER = "Game"
    PIRACY_FOLDERS = ["_CommonRedist", "AdvGuide"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll", "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
        return results


class DarkSouls1Checker(BaseChecker):
    GAME_NAME = "Dark Souls Remastered"
    MANIFEST_KEY = "dark_souls_remastered"
    EXE_NAME = "DarkSoulsRemastered.exe"
    SAVE_FILE_NAME = "DRAKS0005.sl2"
    GAME_SUBFOLDER = ""  # flat — files sit directly in install root
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll",
    ]


class DarkSouls2Checker(BaseChecker):
    GAME_NAME = "Dark Souls II: Scholar of the First Sin"
    MANIFEST_KEY = "dark_souls_2"
    EXE_NAME = "DarkSoulsII.exe"
    SAVE_FILE_NAME = "DS2SOFS0000.sl2"
    GAME_SUBFOLDER = "Game"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll",
    ]


class DarkSouls3Checker(BaseChecker):
    GAME_NAME = "Dark Souls III"
    MANIFEST_KEY = "dark_souls_3"
    EXE_NAME = "DarkSoulsIII.exe"
    SAVE_FILE_NAME = "DS30000.sl2"
    GAME_SUBFOLDER = "Game"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll", "dinput8.dll",
    ]

class SekiroChecker(BaseChecker):
    GAME_NAME = "Sekiro: Shadows Die Twice"
    MANIFEST_KEY = "sekiro"
    EXE_NAME = "sekiro.exe"
    SAVE_FILE_NAME = "S0000.sl2"
    GAME_SUBFOLDER = ""  # flat — files sit directly in install root
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll",
    ]


class ArmoredCore6Checker(BaseChecker):
    GAME_NAME = "Armored Core VI: Fires of Rubicon"
    MANIFEST_KEY = "armored_core_6"
    EXE_NAME = "armoredcore6.exe"
    SAVE_FILE_NAME = "AC60000.sl2"
    GAME_SUBFOLDER = "Game"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt", "OnlineFix.ini", "OnlineFix64.dll",
        "steam_api64.rne", "steam_emu.ini", "winmm.dll", "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
        return results