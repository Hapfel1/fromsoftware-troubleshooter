"""Standalone checker - no er_save_manager dependency."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import ssl
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import certifi


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
        # Frozen builds cannot rely on the system CA paths of the build
        # machine, so certificates come from the bundled certifi store.
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(MANIFEST_URL, timeout=3, context=ctx) as resp:
            _MANIFEST_CACHE = json.loads(resp.read().decode())
            _dbg(f"manifest: loaded from remote, keys={list(_MANIFEST_CACHE.keys())}")
            return _MANIFEST_CACHE
    except Exception as e:
        _dbg(f"manifest: remote fetch failed ({e}), trying local")
    # Local fallback: check several likely locations
    candidates = [
        Path(__file__).with_name("game_file_sizes.json"),  # alongside checker.py
        Path(__file__).parent.parent
        / "game_file_sizes.json",  # project root (dev layout)
        Path.cwd() / "game_file_sizes.json",  # working directory
    ]
    for candidate in candidates:
        _dbg(f"manifest: checking {candidate} - exists={candidate.exists()}")
        if candidate.exists():
            try:
                _MANIFEST_CACHE = json.loads(candidate.read_text())
                _dbg(
                    f"manifest: loaded from {candidate}, keys={list(_MANIFEST_CACHE.keys())}"
                )
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
            name="Game Version Check",
            status="info",
            message="No app ID configured for this game",
        )

    _dbg(f"build_id check: manifest_key={manifest_key} stored={stored}")

    if stored == 0:
        return DiagnosticResult(
            name="Game Version Check",
            status="info",
            message="No reference build ID recorded - size checks may not reflect the latest patch",
        )

    current = _read_local_build_id(app_id)
    _dbg(f"build_id check: local ACF build_id={current}")
    if current is None:
        return DiagnosticResult(
            name="Game Version Check",
            status="info",
            message="Game not found in Steam libraries - cannot verify build ID",
        )

    if current != stored:
        return DiagnosticResult(
            name="Game Version Check",
            status="warning",
            message=(
                f"Game has been updated since file sizes were recorded "
                f"(recorded build {stored}, installed build {current}). "
                "Size checks may be inaccurate."
            ),
        )

    return DiagnosticResult(
        name="Game Version Check",
        status="ok",
        message=f"Game is on the expected build ({current})",
    )


def _newer_build_than_recorded(manifest_key: str) -> tuple[int, int] | None:
    """(recorded, installed) build IDs when the installed build is newer."""
    app_id = _APP_IDS.get(manifest_key)
    stored = _load_manifest().get(manifest_key, {}).get("build_id", 0)
    if not app_id or not stored:
        return None
    current = _read_local_build_id(app_id)
    if current is None or current <= stored:
        return None
    return stored, current


def _size_mismatch_result(
    name: str, file_name: str, actual: int, entry: dict | None, manifest_key: str
) -> DiagnosticResult | None:
    """
    Info result for a size mismatch caused by a game update newer than the
    recorded sizes, or None when the mismatch is not explained by an update.
    """
    builds = _newer_build_than_recorded(manifest_key)
    if not builds:
        return None
    expected = _format_size(entry["exact"]) if entry else "unknown"
    return DiagnosticResult(
        name=name,
        status="info",
        message=(
            f"{file_name} size differs from the recorded size "
            f"(found {_format_size(actual)}, recorded {expected}). The game was "
            f"updated since (recorded build {builds[0]}, installed build "
            f"{builds[1]}), so a new size is expected until the reference is "
            "updated."
        ),
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


def _get_runasadmin_scope(exe_path: Path) -> str | None:
    """
    Look up the persistent 'Run as administrator' compatibility flag for
    exe_path in both the per-user and all-users AppCompatFlags registry
    layers. Returns which scope has it set, or None if unset in both.
    """
    import winreg

    exe_paths = {
        os.path.normcase(os.path.normpath(str(exe_path))),
        os.path.normcase(os.path.normpath(str(exe_path.resolve()))),
    }
    layers_path = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    hives = [
        (winreg.HKEY_CURRENT_USER, "current user"),
        (winreg.HKEY_LOCAL_MACHINE, "all users"),
    ]
    views = [0]
    for view_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        view = getattr(winreg, view_name, 0)
        if view not in views:
            views.append(view)

    for hive, scope_label in hives:
        for view in views:
            try:
                key = winreg.OpenKey(hive, layers_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            try:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    normalized_name = os.path.normcase(os.path.normpath(name))
                    if (
                        normalized_name in exe_paths
                        and "RUNASADMIN" in str(value).upper().split()
                    ):
                        return scope_label
            finally:
                winreg.CloseKey(key)
    return None


_process_cache: dict[str, list[int]] | None = None


def clear_caches() -> None:
    """Forget cached processes, Steam libraries and build IDs before a new run."""
    global _process_cache, _library_cache
    _process_cache = None
    _library_cache = None
    _build_id_cache.clear()


def _get_running_processes() -> dict[str, list[int]]:
    """Lowercase running process names mapped to their PIDs, cross-platform."""
    global _process_cache
    if _process_cache is not None:
        return _process_cache
    processes: dict[str, list[int]] = {}
    if _is_windows():
        try:
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in out.splitlines():
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2 and parts[1].isdigit():
                    processes.setdefault(parts[0].lower(), []).append(int(parts[1]))
        except Exception:
            pass
    else:
        # Linux: read /proc/*/comm (process name, max 15 chars) and /proc/*/exe
        proc = Path("/proc")
        for pid_dir in proc.iterdir():
            if not pid_dir.name.isdigit():
                continue
            pid = int(pid_dir.name)
            try:
                name = (pid_dir / "comm").read_text().strip().lower()
                processes.setdefault(name, []).append(pid)
            except OSError:
                pass
            try:
                exe = (pid_dir / "exe").resolve().name.lower()
                pids = processes.setdefault(exe, [])
                if pid not in pids:
                    pids.append(pid)
            except OSError:
                pass
    _process_cache = processes
    return processes


def _get_running_process_names() -> set[str]:
    """Lowercase names of running processes."""
    return set(_get_running_processes())


def _is_process_elevated(pid: int) -> bool | None:
    """
    Whether a Windows process runs elevated, or None if unknown. Access denied
    on the token of a process owned by the same user means it is elevated.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    TOKEN_ELEVATION = 20
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED else None
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED else None
        try:
            elevation = wintypes.DWORD()
            size = wintypes.DWORD()
            if not advapi32.GetTokenInformation(
                token,
                TOKEN_ELEVATION,
                ctypes.byref(elevation),
                ctypes.sizeof(elevation),
                ctypes.byref(size),
            ):
                return None
            return elevation.value != 0
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(process)


def _get_scheduled_problematic_processes() -> list[str]:
    """Return enabled scheduled tasks whose actions launch known processes."""
    if not _is_windows():
        return []
    # Get-ScheduledTask returns language-independent State and Execute values,
    # unlike the localized labels of "schtasks /query /v".
    ps_script = (
        "Get-ScheduledTask -ErrorAction SilentlyContinue | "
        "Where-Object { [string]$_.State -ne 'Disabled' } | "
        "ForEach-Object { foreach ($a in $_.Actions) { "
        'if ($a.Execute) { "$($a.Execute) $($a.Arguments)" } } }'
    )
    try:
        output = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=20,
        ).stdout
    except Exception:
        return []

    matches: list[str] = []
    for action in output.splitlines():
        action = action.strip().casefold()
        if not action:
            continue
        for process in PROBLEMATIC_PROCESSES:
            process_pattern = rf"(?<![\w.-]){re.escape(process.casefold())}(?![\w.-])"
            if re.search(process_pattern, action) and process not in matches:
                matches.append(process)
    return matches


def _is_windows_service_running(service_name: str) -> bool:
    """Whether the named Windows service or kernel driver is running."""
    import ctypes
    from ctypes import wintypes

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [
            ("dwServiceType", wintypes.DWORD),
            ("dwCurrentState", wintypes.DWORD),
            ("dwControlsAccepted", wintypes.DWORD),
            ("dwWin32ExitCode", wintypes.DWORD),
            ("dwServiceSpecificExitCode", wintypes.DWORD),
            ("dwCheckPoint", wintypes.DWORD),
            ("dwWaitHint", wintypes.DWORD),
        ]

    SC_MANAGER_CONNECT = 0x0001
    SERVICE_QUERY_STATUS = 0x0004
    SERVICE_RUNNING = 4

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.OpenSCManagerW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    advapi.OpenSCManagerW.restype = wintypes.HANDLE
    advapi.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    advapi.OpenServiceW.restype = wintypes.HANDLE
    advapi.QueryServiceStatus.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(SERVICE_STATUS),
    ]
    advapi.QueryServiceStatus.restype = wintypes.BOOL
    advapi.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    advapi.CloseServiceHandle.restype = wintypes.BOOL

    scm = advapi.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not scm:
        return False
    try:
        service = advapi.OpenServiceW(scm, service_name, SERVICE_QUERY_STATUS)
        if not service:
            return False
        try:
            status = SERVICE_STATUS()
            if not advapi.QueryServiceStatus(service, ctypes.byref(status)):
                return False
            return status.dwCurrentState == SERVICE_RUNNING
        finally:
            advapi.CloseServiceHandle(service)
    finally:
        advapi.CloseServiceHandle(scm)


def _is_hidhide_service_running() -> bool:
    """Return whether the HidHide kernel service is installed and running."""
    if not _is_windows():
        return False
    try:
        return _is_windows_service_running("HidHide")
    except OSError:
        return False


def _get_running_windows_services(service_names: tuple[str, ...]) -> list[str]:
    """Return the requested Windows services that are currently running."""
    if not _is_windows():
        return []
    running: list[str] = []
    for service_name in service_names:
        try:
            if _is_windows_service_running(service_name):
                running.append(service_name)
        except OSError:
            continue
    return running


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _is_flatpak_steam() -> bool:
    if not _is_linux():
        return False
    return (
        Path.home()
        / ".var"
        / "app"
        / "com.valvesoftware.Steam"
        / ".local"
        / "share"
        / "Steam"
    ).exists()


_library_cache: list[Path] | None = None


def _get_steam_library_folders() -> list[Path]:
    """Return all Steam steamapps directories on this machine."""
    global _library_cache
    if _library_cache is None:
        _library_cache = _scan_steam_library_folders()
    return list(_library_cache)


def _scan_steam_library_folders() -> list[Path]:
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
                try:
                    if stem.exists():
                        libraries.append(stem)
                except OSError:
                    pass

    elif _is_linux():
        for candidate in (
            Path.home() / ".local" / "share" / "Steam" / "steamapps",
            Path.home() / ".steam" / "steam" / "steamapps",
            Path.home()
            / ".var"
            / "app"
            / "com.valvesoftware.Steam"
            / ".local"
            / "share"
            / "Steam"
            / "steamapps",
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
    "elden_ring": "1245620",
    "nightreign": "2622380",
    "dark_souls_remastered": "570940",
    "dark_souls_2": "335300",
    "dark_souls_3": "374320",
    "sekiro": "814380",
    "armored_core_6": "1888160",
}

# Subfolder inside AppData/Roaming (Windows) or Wine prefix equivalent (Linux)
_SAVE_ROAMING_SUBPATHS: dict[str, str] = {
    "elden_ring": "EldenRing",
    "nightreign": "NightReign",
    "dark_souls_remastered": "DarkSoulsRemastered",
    "dark_souls_2": "DarkSoulsII/SOFTS",
    "dark_souls_3": "DarkSoulsIII",
    "sekiro": "Sekiro",
    "armored_core_6": "ArmoredCore6",
}

_SAVE_FILENAMES: dict[str, str] = {
    "elden_ring": "ER0000.sl2",
    "nightreign": "NR0000.sl2",
    "dark_souls_remastered": "DRAKS0005.sl2",
    "dark_souls_2": "DS2SOFS0000.sl2",
    "dark_souls_3": "DS30000.sl2",
    "sekiro": "S0000.sl2",
    "armored_core_6": "AC60000.sl2",
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
            Path("pfx")
            / "drive_c"
            / "users"
            / "steamuser"
            / "AppData"
            / "Roaming"
            / subpath
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
        p for p in candidates if p.is_file() and p.suffix not in _BACKUP_EXTENSIONS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def windows_save_root(manifest_key: str) -> Path | None:
    """The game's top-level save folder under %APPDATA% on Windows."""
    subpath = _SAVE_ROAMING_SUBPATHS.get(manifest_key)
    if not subpath:
        return None
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / subpath.split("/")[0]


def permission_fix_commands(game_folder: Path | None, manifest_key: str) -> list[str]:
    """takeown/icacls commands for the game folder and its save folder."""
    username = os.environ.get("USERNAME", "YourUsername")
    folders = [game_folder, windows_save_root(manifest_key)]
    commands: list[str] = []
    for folder in folders:
        if folder is None:
            continue
        commands.append(f'takeown /F "{folder}" /R /D Y')
        commands.append(f'icacls "{folder}" /grant "{username}":F /T')
    return commands


def get_linux_launch_options(manifest_key: str, game_folder: Path | None) -> str | None:
    """Build Steam Linux launch options for the detected game's library."""
    app_id = _APP_IDS.get(manifest_key)
    if not app_id or not game_folder:
        return None

    try:
        game_folder = game_folder.resolve()
    except OSError:
        pass

    library_path: Path | None = None
    for steamapps in _get_steam_library_folders():
        try:
            game_folder.relative_to(steamapps / "common")
        except ValueError:
            continue
        library_path = steamapps
        break

    if library_path is None:
        candidate = game_folder.parent.parent
        if candidate.name == "steamapps":
            library_path = candidate
    if library_path is None:
        return None

    try:
        relative_to_home = library_path.relative_to(Path.home())
    except ValueError:
        library_value = shlex.quote(f"{library_path}/")
    else:
        library_value = f"$HOME/{relative_to_home}/"

    return (
        f"STEAM_COMPAT_LIBRARY_PATHS={library_value} "
        f"STEAM_COMPAT_DATA_PATH=$STEAM_COMPAT_LIBRARY_PATHS/compatdata/{app_id}/ "
        f"SteamAppId={app_id} SteamGameId={app_id} "
        f"SteamOverlayGameId={app_id} %command%"
    )


# ---------------------------------------------------------------------------
# Process lists
# ---------------------------------------------------------------------------

# High confidence - known to cause crashes or EAC issues
PROBLEMATIC_PROCESSES = [
    # Windows
    "vgtray.exe",
    "RTSS.exe",
    "RTSSHooksLoader64.exe",
    "SystemExplorer.exe",
    "MSIAfterburner.exe",
    "SignalRgb.exe",
    "ProcessLasso.exe",
    "HidHideClient.exe",
    "MacTray.exe",
    "FileXplorer.exe",
    # Problematic antiviruses (known to cause crashes, false bans, or performance issues)
    "avira.exe",
    "avgui.exe",
    "AviraOptimizerHost.exe",
    "AviraSecurityCenterAgent.exe",
    "Norton.exe",
    "NortonSecurity.exe",
    "avast.exe",
    "AvastUI.exe",
    "AvastSvc.exe",
    "avgnt.exe",
    "AVGSvc.exe",
    "mcshield.exe",
    "mcuicnt.exe",  # McAfee
    "ekrn.exe",
    "egui.exe",  # ESET
    "TrusteerEndpointProtection.exe",  # Trusteer Rapport
]

# Low confidence - unlikely to cause issues but worth knowing
INFORMATIONAL_PROCESSES = [
    # Windows
    "Overwolf.exe",
    "Medal.exe",
    "GeForceExperience.exe",
    "XboxGameBar.exe",
    "GameBarFTServer.exe",
    "EpicGamesLauncher.exe",
    "GalaxyClient.exe",
]

VPN_PROCESSES = [
    # Windows
    "NordVPN.exe",
    "nordvpn-service.exe",
    "expressvpn.exe",
    "expressvpnd.exe",
    "surfshark.exe",
    "SurfsharkService.exe",
    "protonvpn.exe",
    "ProtonVPN.exe",
    "CyberGhost.exe",
    "CG7Service.exe",
    "pia-client.exe",
    "pia-service.exe",
    "windscribe.exe",
    "windscribeservice.exe",
    "TunnelBear.exe",
    "TunnelBearService.exe",
    "hsscp.exe",
    "IPVanish.exe",
    "AtlasVPN.exe",
    "Cloudflare WARP.exe",
    "warp-svc.exe",
    "hamachi-2.exe",
    "hamachi-2-ui.exe",
    "Radmin VPN.exe",
    "RvpnService.exe",
    # Linux
    "nordvpnd",
    "nordvpn",
    "expressvpn",
    "protonvpn",
    "mullvad",
    "mullvad-vpn",
    "mullvad-daemon",
    "mullvad-gui",
    "windscribe",
    "windscribed",
    "openvpn",
    "openconnect",
    "wg-quick",
]


CheckOutput = DiagnosticResult | list[DiagnosticResult] | None


def run_check(name: str, check: Callable[[], CheckOutput]) -> list[DiagnosticResult]:
    """Run one check; an exception becomes a warning result named `name`."""
    try:
        output = check()
    except Exception as e:
        _dbg(f"check {name} raised {e!r}")
        output = DiagnosticResult(
            name=name,
            status="warning",
            message=f"This check could not run: {e}",
        )
    if output is None:
        return []
    return output if isinstance(output, list) else [output]


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
    # Seamless Co-op file prefix (e.g. "ersc", "nrsc", "ds1sc", "ds3sc"), or
    # None if no Seamless Co-op mod exists for this game.
    SEAMLESS_COOP_PREFIX: str | None = None

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

    def checks(self) -> list[tuple[str, Callable[[], CheckOutput]]]:
        """Checks in display order, as (name shown if it fails, callable)."""
        folder_ok = bool(self.game_folder and self.game_folder.exists())
        checks: list[tuple[str, Callable[[], CheckOutput]]] = [
            ("Game Installation", self._check_game_installation),
            ("Game Version Check", lambda: check_build_id(self.MANIFEST_KEY)),
            ("Steam Status", self._check_steam_running),
        ]
        if folder_ok:
            checks += [
                ("Game Executable", self._check_game_executable),
                ("Run as Administrator Flag", self._check_run_as_admin_flag),
            ]
        checks.append(("Game-Specific Checks", self._check_extra))
        if folder_ok:
            checks.append(("Game Integrity", self._check_piracy_indicators))
        checks += [
            ("Process Check", self._check_problematic_processes),
            ("VPN Check", self._check_vpn_processes),
            ("Steam Elevation Check", self._check_steam_elevated),
            ("Save File", self._check_save_file_health),
            ("Disk Space", self._check_disk_space),
        ]
        return checks

    def run_all_checks(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        for name, check in self.checks():
            results.extend(run_check(name, check))
        return results

    def _check_extra(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        if _is_windows():
            results.append(self._check_fasoo())
            hidhide = self._check_hidhide_service()
            if hidhide:
                results.append(hidhide)
            vanguard = _get_running_windows_services(("vgk", "vgc"))
            if vanguard:
                results.append(
                    DiagnosticResult(
                        name="Riot Vanguard Running",
                        status="warning",
                        message=(
                            "Riot Vanguard is active ("
                            f"{', '.join(vanguard)}). Its kernel-level anti-cheat "
                            "can conflict with FromSoftware games."
                        ),
                        fix_available=True,
                        fix_action=(
                            "Exit Riot Vanguard from the system tray, or uninstall "
                            "Riot Vanguard temporarily, then restart Windows."
                        ),
                    )
                )
            rtcore = _get_running_windows_services(("RTCore64",))
            if rtcore:
                results.append(
                    DiagnosticResult(
                        name="RTCore64 Driver Running",
                        status="warning",
                        message=(
                            "The RTCore64 kernel driver is active, usually from "
                            "MSI Afterburner or RivaTuner Statistics Server."
                        ),
                        fix_available=True,
                        fix_action=(
                            "Exit MSI Afterburner and RivaTuner Statistics Server "
                            "before launching the game."
                        ),
                    )
                )
        return results

    def _check_firewall_block(self) -> DiagnosticResult | None:
        """Check for enabled Windows Firewall block rules for the game's executables."""
        if not _is_windows():
            return None

        game_dir = self._game_dir
        if not game_dir or not self.EXE_NAME:
            return DiagnosticResult(
                name="Firewall Rule Check",
                status="info",
                message="Game folder not set - cannot check firewall rules",
            )

        executable_paths: list[Path] = []
        exe_path = game_dir / self.EXE_NAME
        if exe_path.exists():
            executable_paths.append(exe_path)
        if self.SEAMLESS_COOP_PREFIX:
            launcher_path = _find_seamless_coop_artifacts(
                game_dir, self.SEAMLESS_COOP_PREFIX
            )[2]
            if launcher_path:
                executable_paths.append(launcher_path)
        if not executable_paths:
            return DiagnosticResult(
                name="Firewall Rule Check",
                status="info",
                message=f"{self.EXE_NAME} not found - cannot check firewall rules",
            )

        # Filters by program first and resolves rules only for matching
        # filters; one Get-NetFirewallApplicationFilter call per block rule is
        # too slow on systems with many rules.
        ps_script = r"""
function Normalize([string]$path) {
    ([Environment]::ExpandEnvironmentVariables($path)).Trim().Trim('"').Replace('/', '\').ToLowerInvariant()
}
$programs = @($env:FST_FIREWALL_PROGRAMS -split "`n" | Where-Object { $_ } | ForEach-Object { Normalize $_ })
$found = @(
    Get-NetFirewallApplicationFilter -ErrorAction Stop |
        Where-Object { $programs -contains (Normalize $_.Program) } |
        ForEach-Object {
            $program = Normalize $_.Program
            Get-NetFirewallRule -AssociatedNetFirewallApplicationFilter $_ |
                Where-Object { [string]$_.Enabled -eq 'True' -and [string]$_.Action -eq 'Block' } |
                ForEach-Object {
                    [PSCustomObject]@{
                        Name = $_.DisplayName
                        Direction = [string]$_.Direction
                        Program = $program
                    }
                }
        }
)
if ($found.Count -eq 0) { '[]' } else { $found | ConvertTo-Json -Compress }
"""
        env = os.environ.copy()
        env["FST_FIREWALL_PROGRAMS"] = "\n".join(str(path) for path in executable_paths)
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=30,
            )
            if result.returncode != 0:
                return DiagnosticResult(
                    name="Firewall Rule Check",
                    status="warning",
                    message="Could not query Windows Firewall rules",
                )
            raw = result.stdout.strip()
            rules = json.loads(raw) if raw else []
            if isinstance(rules, dict):
                rules = [rules]
            bullets = [
                f"{rule.get('Name', 'Unnamed rule')} ({rule.get('Direction', 'Unknown').lower()})"
                for rule in rules
            ]
            if bullets:
                executable_names = ", ".join(path.name for path in executable_paths)
                return DiagnosticResult(
                    name="Game Firewall Block Rule Detected",
                    status="warning",
                    message=(
                        f"Enabled Windows Firewall block rules target {executable_names}. "
                        "They can force the game offline and prevent multiplayer connectivity."
                    ),
                    bullet_items=bullets,
                    fix_available=True,
                    fix_action=(
                        "Open Windows Defender Firewall with Advanced Security, "
                        "find the listed inbound or outbound block rules, and disable "
                        "or remove them. Then restart the game."
                    ),
                )
            return DiagnosticResult(
                name="Firewall Rule Check",
                status="ok",
                message=(
                    "No enabled Windows Firewall block rules target "
                    f"{', '.join(path.name for path in executable_paths)}"
                ),
            )
        except subprocess.TimeoutExpired:
            return DiagnosticResult(
                name="Firewall Rule Check",
                status="info",
                message="Windows Firewall rule check timed out; no result available",
            )
        except (OSError, json.JSONDecodeError) as e:
            return DiagnosticResult(
                name="Firewall Rule Check",
                status="info",
                message=f"Could not query Windows Firewall rules: {e}",
            )

    def _check_hidhide_service(self) -> DiagnosticResult | None:
        if not _is_hidhide_service_running():
            return None
        return DiagnosticResult(
            name="HidHide Service Running",
            status="warning",
            message=(
                "HidHide's kernel service is running. Its device filtering can "
                "interfere with controller detection in FromSoftware games."
            ),
            fix_available=True,
            fix_action=(
                "Open HidHide Configuration Client, disable device hiding, "
                "then restart the game."
            ),
        )

    def _check_fasoo(self) -> DiagnosticResult:
        """
        Detect Fasoo DRM by checking known install locations on disk, then
        scanning the game process modules as a secondary signal if the game
        is running. Fasoo injects into other processes, not the checker itself,
        so scanning the checker's own loaded modules is useless.
        """
        import ctypes
        import ctypes.wintypes

        # Known Fasoo DLL names (32-bit and 64-bit client, virtual rights component)
        FASOO_DLLS = {"f_im.dll", "f_im64.dll", "fsvrt.dll"}

        FIX = "Uninstall Fasoo DRM Client (Kyobo Book Wix or similar) and reboot."

        # Primary: disk presence in known Fasoo install directories
        program_files = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        ]
        found_on_disk: list[str] = []
        for base in program_files:
            fasoo_dir = base / "Fasoo"
            if not fasoo_dir.exists():
                continue
            for dll in FASOO_DLLS:
                if (fasoo_dir / dll).exists():
                    found_on_disk.append(str(fasoo_dir / dll))

        if found_on_disk:
            return DiagnosticResult(
                name="Fasoo DRM Detected",
                status="error",
                message=(
                    "Fasoo DRM is installed. It is known to cause crashes and "
                    "infinite loading screens in FromSoftware games by injecting "
                    f"into game processes. Found: {', '.join(found_on_disk)}"
                ),
                fix_available=True,
                fix_action=FIX,
            )

        # Secondary: scan game process modules if the game is running
        if self.EXE_NAME:
            try:
                k32 = ctypes.windll.kernel32
                psapi = ctypes.windll.psapi
                wintypes = ctypes.wintypes

                # Find the game PID by iterating snapshot of processes
                TH32CS_SNAPPROCESS = 0x00000002

                class PROCESSENTRY32(ctypes.Structure):
                    _fields_ = [
                        ("dwSize", ctypes.c_ulong),
                        ("cntUsage", ctypes.c_ulong),
                        ("th32ProcessID", ctypes.c_ulong),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", ctypes.c_ulong),
                        ("cntThreads", ctypes.c_ulong),
                        ("th32ParentProcessID", ctypes.c_ulong),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", ctypes.c_ulong),
                        ("szExeFile", ctypes.c_char * 260),
                    ]

                k32.CreateToolhelp32Snapshot.argtypes = [
                    wintypes.DWORD,
                    wintypes.DWORD,
                ]
                k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
                k32.Process32First.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(PROCESSENTRY32),
                ]
                k32.Process32First.restype = wintypes.BOOL
                k32.Process32Next.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(PROCESSENTRY32),
                ]
                k32.Process32Next.restype = wintypes.BOOL
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle.restype = wintypes.BOOL
                k32.OpenProcess.argtypes = [
                    wintypes.DWORD,
                    wintypes.BOOL,
                    wintypes.DWORD,
                ]
                k32.OpenProcess.restype = wintypes.HANDLE
                psapi.EnumProcessModules.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(wintypes.HMODULE),
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                ]
                psapi.EnumProcessModules.restype = wintypes.BOOL
                psapi.GetModuleBaseNameW.argtypes = [
                    wintypes.HANDLE,
                    wintypes.HMODULE,
                    wintypes.LPWSTR,
                    wintypes.DWORD,
                ]
                psapi.GetModuleBaseNameW.restype = wintypes.DWORD

                snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
                if snapshot == ctypes.c_void_p(-1).value:
                    raise OSError("CreateToolhelp32Snapshot failed")

                game_pid: int | None = None
                entry = PROCESSENTRY32()
                entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
                try:
                    if k32.Process32First(snapshot, ctypes.byref(entry)):
                        while True:
                            name = entry.szExeFile.decode("utf-8", errors="ignore")
                            if name.lower() == self.EXE_NAME.lower():
                                game_pid = entry.th32ProcessID
                                break
                            if not k32.Process32Next(snapshot, ctypes.byref(entry)):
                                break
                finally:
                    k32.CloseHandle(snapshot)

                if game_pid is not None:
                    PROCESS_QUERY_INFORMATION = 0x0400
                    PROCESS_VM_READ = 0x0010
                    hProcess = k32.OpenProcess(
                        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, game_pid
                    )
                    if hProcess:
                        try:
                            HMODULE_ARR = ctypes.c_void_p * 1024
                            hMods = HMODULE_ARR()
                            cbNeeded = ctypes.c_ulong()
                            if psapi.EnumProcessModules(
                                hProcess,
                                hMods,
                                ctypes.sizeof(hMods),
                                ctypes.byref(cbNeeded),
                            ):
                                count = cbNeeded.value // ctypes.sizeof(ctypes.c_void_p)
                                for i in range(count):
                                    buf = ctypes.create_unicode_buffer(260)
                                    if psapi.GetModuleBaseNameW(
                                        hProcess, hMods[i], buf, 260
                                    ):
                                        if buf.value.lower() in FASOO_DLLS:
                                            return DiagnosticResult(
                                                name="Fasoo DRM Detected",
                                                status="error",
                                                message=(
                                                    f"Fasoo DRM ({buf.value}) is loaded inside "
                                                    f"{self.EXE_NAME}. This causes crashes and "
                                                    "infinite loading screens."
                                                ),
                                                fix_available=True,
                                                fix_action=FIX,
                                            )
                        finally:
                            k32.CloseHandle(hProcess)
            except Exception as e:
                return DiagnosticResult(
                    name="Fasoo DRM Check",
                    status="warning",
                    message=f"Could not scan game process modules for Fasoo DRM: {e}",
                )

        return DiagnosticResult(
            name="Fasoo DRM Check",
            status="ok",
            message="No Fasoo DRM detected",
        )

    def _check_game_installation(self) -> DiagnosticResult:
        if not self.game_folder:
            return DiagnosticResult(
                name="Game Installation",
                status="warning",
                message="Game folder not found automatically",
                fix_available=True,
                fix_action="Use Set Game Folder to select the game's install folder.",
            )
        if not self.game_folder.exists():
            return DiagnosticResult(
                name="Game Installation",
                status="error",
                message=f"Game folder not found: {self.game_folder}",
            )
        return DiagnosticResult(
            name="Game Installation",
            status="ok",
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
                name="Game Executable",
                status="error",
                message=f"{self.EXE_NAME} not found in {game_dir}",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        actual_size = exe_path.stat().st_size
        size_status = _check_file_size(exe_path, self.MANIFEST_KEY, "exe")
        entry = _get_size_entry(self.MANIFEST_KEY, "exe")

        if size_status == "ok":
            return DiagnosticResult(
                name="Game Executable",
                status="ok",
                message=f"{self.EXE_NAME} found - {_format_size(actual_size)}",
            )
        elif size_status == "warning":
            updated = _size_mismatch_result(
                "Game Executable", self.EXE_NAME, actual_size, entry, self.MANIFEST_KEY
            )
            if updated:
                return updated
            expected = _format_size(entry["exact"]) if entry else "unknown"
            return DiagnosticResult(
                name="Game Executable",
                status="warning",
                message=(
                    f"{self.EXE_NAME} size is unexpected.\n"
                    f"Found: {_format_size(actual_size)}\n"
                    f"Expected: {expected}"
                ),
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        return DiagnosticResult(
            name="Game Executable",
            status="info",
            message=f"{self.EXE_NAME} found - {_format_size(actual_size)} (no reference size available)",
        )

    def _check_run_as_admin_flag(self) -> DiagnosticResult | None:
        """
        Check the persistent 'Run as administrator' compatibility flag on the
        game executable. Windows-only concept, so this is hidden entirely on
        other platforms rather than shown as an info row.
        """
        if not _is_windows():
            return None
        game_dir = self._game_dir
        if not game_dir or not self.EXE_NAME:
            return DiagnosticResult(
                name="Run as Administrator Flag",
                status="info",
                message="Game folder not set",
            )
        exe_path = game_dir / self.EXE_NAME
        if not exe_path.exists():
            return DiagnosticResult(
                name="Run as Administrator Flag",
                status="info",
                message=f"{self.EXE_NAME} not found, skipping compatibility flag check",
            )

        scope = _get_runasadmin_scope(exe_path)
        if scope:
            return DiagnosticResult(
                name="Run as Administrator Flag",
                status="error",
                message=(
                    f"{self.EXE_NAME} is set to always run as administrator "
                    f"({scope}). This causes permission issues and is not recommended"
                ),
                fix_available=True,
                fix_action=(
                    f"Right-click {self.EXE_NAME} > Properties > Compatibility tab\n"
                    "-> Uncheck 'Run this program as an administrator'\n"
                    "If the checkbox is greyed out, the flag is set for all users: "
                    "click 'Change settings for all users' first."
                ),
            )
        return DiagnosticResult(
            name="Run as Administrator Flag",
            status="ok",
            message=f"{self.EXE_NAME} is not flagged to run as administrator",
        )

    def _check_seamless_coop_launcher_admin_flag(self) -> DiagnosticResult | None:
        """
        The Seamless Co-op launcher is a separate executable from the game
        exe and carries its own independent run-as-administrator flag. Only
        checked when the launcher is actually present, and only reported
        when the flag is set, since a correct setup needs no callout here.
        """
        if not self.SEAMLESS_COOP_PREFIX or not _is_windows():
            return None
        game_dir = self._game_dir
        if not game_dir:
            return None
        launcher_name = f"{self.SEAMLESS_COOP_PREFIX}_launcher.exe"
        launcher_path = game_dir / launcher_name
        if not launcher_path.exists():
            return None
        scope = _get_runasadmin_scope(launcher_path)
        if not scope:
            return None
        return DiagnosticResult(
            name="Run as Administrator Flag",
            status="error",
            message=(
                f"{launcher_name} is set to always run as administrator "
                f"({scope}). This causes permission issues and is not recommended."
            ),
            fix_available=True,
            fix_action=(
                f"Right-click {launcher_name} > Properties > Compatibility tab\n"
                "-> Uncheck 'Run this program as an administrator'\n"
                "If the checkbox is greyed out, the flag is set for all users: "
                "click 'Change settings for all users' first."
            ),
        )

    def _check_seamless_coop(self) -> list[DiagnosticResult]:
        """
        Detect a Seamless Co-op install and report only actual problems.
        No install and a correct install both produce no results.
        """
        if not self.SEAMLESS_COOP_PREFIX:
            return []
        game_dir = self._game_dir
        if not game_dir or not game_dir.exists():
            return []

        prefix = self.SEAMLESS_COOP_PREFIX
        dll_name = f"{prefix}.dll"
        ini_name = f"{prefix}_settings.ini"
        launcher_name = f"{prefix}_launcher.exe"

        expected_dll = game_dir / "SeamlessCoop" / dll_name
        expected_ini = game_dir / "SeamlessCoop" / ini_name
        expected_launcher = game_dir / launcher_name

        any_seamless_trace = (
            expected_dll.exists()
            or expected_launcher.exists()
            or (game_dir / "SeamlessCoop").exists()
            or any(
                "seamless" in entry.name.lower()
                for entry in game_dir.iterdir()
                if entry.is_dir()
            )
        )
        if not any_seamless_trace:
            return []

        if (
            expected_dll.exists()
            and expected_ini.exists()
            and expected_launcher.exists()
        ):
            return self._check_seamless_coop_password(expected_ini)

        found_dll, found_ini, found_launcher = _find_seamless_coop_artifacts(
            game_dir, prefix
        )

        bullets: list[str] = []
        if expected_dll.exists():
            pass
        elif found_dll:
            bullets.append(
                f"{dll_name} found at wrong location: {found_dll.relative_to(game_dir)}"
            )
        else:
            bullets.append(f"{dll_name} not found anywhere in the game folder")

        if expected_ini.exists():
            pass
        elif found_ini:
            bullets.append(
                f"{ini_name} found at wrong location: {found_ini.relative_to(game_dir)}"
            )
        else:
            bullets.append(f"{ini_name} not found anywhere in the game folder")

        if expected_launcher.exists():
            pass
        elif found_launcher:
            bullets.append(
                f"{launcher_name} found at wrong location: "
                f"{found_launcher.relative_to(game_dir)}"
            )
        else:
            bullets.append(f"{launcher_name} not found anywhere in the game folder")

        tree_prefix = f"{self.GAME_SUBFOLDER}/" if self.GAME_SUBFOLDER else ""
        return [
            DiagnosticResult(
                name="Seamless Co-op Installation",
                status="error",
                message="Seamless Co-op is not set up correctly:",
                bullet_items=bullets,
                fix_available=True,
                fix_action=(
                    "The release zip extracts into its own wrapper folder. Open that "
                    "extracted folder and move only its contents (the SeamlessCoop "
                    f"folder and {launcher_name}) directly into the game folder next "
                    f"to {self.EXE_NAME}, then delete the now-empty wrapper folder. "
                    "The result should look like:\n"
                    f"{tree_prefix}{self.EXE_NAME}\n"
                    f"{tree_prefix}{launcher_name}\n"
                    f"{tree_prefix}SeamlessCoop/{dll_name}\n"
                    f"{tree_prefix}SeamlessCoop/{ini_name}"
                ),
            )
        ]

    def _check_seamless_coop_password(self, ini_path: Path) -> list[DiagnosticResult]:
        ini_name = ini_path.name
        try:
            ini_text = ini_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            return [
                DiagnosticResult(
                    name="Seamless Co-op Settings",
                    status="warning",
                    message=f"Could not read {ini_name}: {e}",
                )
            ]

        password_match = re.search(
            r"(?im)^[ \t]*cooppassword[ \t]*=[ \t]*(.*?)[ \t]*\r?$", ini_text
        )
        password = password_match.group(1).strip() if password_match else ""
        if password:
            return []
        return [
            DiagnosticResult(
                name="Seamless Co-op Password",
                status="error",
                message=(
                    f"cooppassword in {ini_name} is empty, the mod will "
                    "refuse to launch. A common cause on Windows 11: Notepad "
                    "only caches the file and does not automatically save it "
                    "when closing."
                ),
                fix_available=True,
                fix_action=(
                    f"Open SeamlessCoop/{ini_name}, set cooppassword to any "
                    "value, then use File > Save or Ctrl+S and close it"
                ),
            )
        ]

    def _check_piracy_indicators(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        game_dir = self._game_dir
        if not game_dir or not game_dir.exists():
            return results

        found_folders = [f for f in self.PIRACY_FOLDERS if (game_dir / f).exists()]
        if found_folders:
            results.append(
                DiagnosticResult(
                    name="Unsupported Folders Detected",
                    status="warning",
                    message="Found unsupported folders in the game directory:",
                    bullet_items=list(found_folders),
                )
            )

        found_files: list[str] = []
        # Check game_dir, parent, and immediate subdirectories (piracy files can be anywhere)
        search_dirs = [(game_dir, "")]
        if game_dir.parent != game_dir:
            search_dirs.append((game_dir.parent, "../"))
        # Check immediate subdirectories (some repacks nest folders)
        for subdir in game_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("."):
                search_dirs.append((subdir, f"{subdir.name}/"))

        for f in self.PIRACY_FILES:
            for search_dir, prefix in search_dirs:
                if (search_dir / f).exists():
                    rel_path = f"{prefix}{f}" if prefix else f
                    if rel_path not in found_files:
                        found_files.append(rel_path)
                    break

        steam_api = game_dir / "steam_api64.dll"
        if steam_api.exists():
            size_status = _check_file_size(
                steam_api, self.MANIFEST_KEY, "steam_api64.dll"
            )
            if size_status == "warning":
                actual = steam_api.stat().st_size
                found_files.append(
                    f"steam_api64.dll (unexpected size: {actual:,} bytes)"
                )
        else:
            results.append(
                DiagnosticResult(
                    name="Critical File Missing",
                    status="error",
                    message="steam_api64.dll is missing from game folder",
                    fix_available=True,
                    fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
                )
            )

        if found_files:
            results.append(
                DiagnosticResult(
                    name="Unsupported/Damaged Files Detected",
                    status="error",
                    message="Found unsupported or modified files in the game directory:",
                    bullet_items=list(found_files),
                    fix_available=True,
                    fix_action="Delete the unsupported files and verify game integrity via Steam.",
                )
            )
        else:
            results.append(
                DiagnosticResult(
                    name="Game Integrity",
                    status="ok",
                    message="No integrity issues detected",
                )
            )
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
                name="Critical File Missing",
                status="error",
                message="regulation.bin is missing from game folder",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        actual_size = regulation.stat().st_size
        size_status = _check_file_size(regulation, self.MANIFEST_KEY, "regulation.bin")
        entry = _get_size_entry(self.MANIFEST_KEY, "regulation.bin")

        if size_status == "ok":
            return DiagnosticResult(
                name="Regulation File",
                status="ok",
                message=f"regulation.bin is valid - {_format_size(actual_size)}",
            )
        elif size_status == "warning":
            updated = _size_mismatch_result(
                "Regulation File",
                "regulation.bin",
                actual_size,
                entry,
                self.MANIFEST_KEY,
            )
            if updated:
                return updated
            expected = _format_size(entry["exact"]) if entry else "unknown"
            return DiagnosticResult(
                name="Regulation File",
                status="warning",
                message=(
                    f"regulation.bin size is unexpected. May indicate modified game files.\n"
                    f"Found: {_format_size(actual_size)}\n"
                    f"Expected: {expected}"
                ),
                fix_available=True,
                fix_action="Delete the file and verify game integrity via Steam.",
            )
        return DiagnosticResult(
            name="Regulation File",
            status="info",
            message=f"regulation.bin found - {_format_size(actual_size)} (no reference size available)",
        )

    def _check_problematic_processes(self) -> list[DiagnosticResult]:
        try:
            running_names = _get_running_process_names()
        except Exception as e:
            return [
                DiagnosticResult(
                    name="Process Check",
                    status="warning",
                    message=f"Could not check processes: {e}",
                )
            ]

        running = [
            p
            for p in PROBLEMATIC_PROCESSES
            if p.lower().replace(".exe", "")
            in {n.replace(".exe", "") for n in running_names}
        ]
        info_running = [
            p
            for p in INFORMATIONAL_PROCESSES
            if p.lower().replace(".exe", "")
            in {n.replace(".exe", "") for n in running_names}
        ]

        scheduled_problematic = _get_scheduled_problematic_processes()

        results: list[DiagnosticResult] = []

        if running:
            fix = (
                "Close these apps before playing, and disable them in Task Manager > Startup tab."
                if _is_windows()
                else "Close these apps before launching the game."
            )
            results.append(
                DiagnosticResult(
                    name="Problematic Processes Running",
                    status="warning",
                    message="The following processes can cause crashes or connection issues:",
                    bullet_items=list(running),
                    fix_available=True,
                    fix_action=fix,
                )
            )

        process_lasso_scheduled = any(
            "processlasso" in process.lower() for process in scheduled_problematic
        )
        if any("processlasso" in p.lower() for p in running) or process_lasso_scheduled:
            results.append(
                DiagnosticResult(
                    name="Process Lasso Detected",
                    status="error",
                    message="Process Lasso can cause flashbang crashes on launch.",
                    fix_available=True,
                    fix_action="1. Close Process Lasso if running\n2. Disable in Task Manager > Startup tab\n3. Remove from Task Scheduler > Task Scheduler Library",
                )
            )

        other_scheduled = [
            process
            for process in scheduled_problematic
            if "processlasso" not in process.lower()
        ]
        if other_scheduled:
            results.append(
                DiagnosticResult(
                    name="Problematic Scheduled Tasks Detected",
                    status="warning",
                    message="These scheduled tasks reference processes that can cause crashes or connection issues:",
                    bullet_items=other_scheduled,
                    fix_available=True,
                    fix_action="Review or disable the matching entries in Task Scheduler > Task Scheduler Library before playing.",
                )
            )

        if info_running:
            results.append(
                DiagnosticResult(
                    name="Low-Priority Processes",
                    status="info",
                    message="These are running but very unlikely to cause issues:",
                    bullet_items=list(info_running),
                )
            )

        if not running and not scheduled_problematic:
            results.append(
                DiagnosticResult(
                    name="Process Check",
                    status="ok",
                    message="No problematic processes detected",
                )
            )

        return results

    def _check_vpn_processes(self) -> list[DiagnosticResult]:
        try:
            running_names = _get_running_process_names()
        except Exception as e:
            return [
                DiagnosticResult(
                    name="VPN Check",
                    status="warning",
                    message=f"Could not check for VPN processes: {e}",
                )
            ]

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
                n == proc_norm
                or n.startswith(proc_norm + "-")
                or proc_norm.startswith(n + "-")
                for n in normalised_running
            )
            if matched:
                seen.add(base)
                running_vpns.append(proc_norm)

        if running_vpns:
            return [
                DiagnosticResult(
                    name="VPN Detected",
                    status="warning",
                    message="Active VPN client(s) detected - may cause multiplayer issues:",
                    bullet_items=running_vpns,
                    fix_available=True,
                    fix_action="Disable or exit your VPN before playing online.",
                )
            ]
        return [
            DiagnosticResult(
                name="VPN Check",
                status="ok",
                message="No VPN clients detected",
            )
        ]

    def _check_steam_running(self) -> DiagnosticResult:
        """Check if Steam is running (cross-platform)."""
        try:
            running_names = _get_running_process_names()
        except Exception:
            return DiagnosticResult(
                name="Steam Status",
                status="info",
                message="Could not check if Steam is running",
            )

        steam_running = any("steam" in name for name in running_names)

        if steam_running:
            return DiagnosticResult(
                name="Steam Status",
                status="ok",
                message="Steam is running",
            )
        return DiagnosticResult(
            name="Steam Status",
            status="info",
            message="Steam is not currently running",
        )

    def _check_steam_elevated(self) -> DiagnosticResult | None:
        if not _is_windows():
            return None
        steam_pids = _get_running_processes().get("steam.exe", [])
        if not steam_pids:
            return DiagnosticResult(
                name="Steam Elevation Check",
                status="info",
                message="Steam is not running (elevation check skipped)",
            )
        states = [_is_process_elevated(pid) for pid in steam_pids]
        if any(state is True for state in states):
            steps = [
                "Steam is running with administrator privileges.",
                "",
                "1. Exit Steam completely",
                "",
                "2. Right-click steam.exe > Properties > Compatibility tab",
                "   -> Uncheck 'Run this program as an administrator'",
                "",
                f"3. Right-click {self.EXE_NAME} in the game folder > Properties > "
                "Compatibility tab",
                "   -> Uncheck 'Run this program as an administrator'",
                "",
                "4. Take Ownership (PowerShell as Admin):",
                "",
                *permission_fix_commands(self.game_folder, self.MANIFEST_KEY),
                "",
                "5. If issues persist:",
                "   - Reinstall Steam (download the installer from steampowered.com "
                "and run it)",
                "   - OR: In Steam, uninstall the game, delete the game folder"
                + (f" {self.game_folder}" if self.game_folder else "")
                + ", restart Steam and reinstall the game",
            ]
            return DiagnosticResult(
                name="Steam Running as Administrator",
                status="error",
                message="Steam is running with elevated privileges. This causes permission issues.",
                fix_available=True,
                fix_action="\n".join(steps),
            )
        if all(state is False for state in states):
            return DiagnosticResult(
                name="Steam Elevation Check",
                status="ok",
                message="Steam is running with normal privileges",
            )
        return DiagnosticResult(
            name="Steam Elevation Check",
            status="warning",
            message="Could not determine if Steam is elevated",
        )

    def _check_save_file_health(self) -> list[DiagnosticResult]:
        if self.save_file_path is None:
            self.save_file_path = find_save_file(self.MANIFEST_KEY)
        if self.save_file_path is None:
            return []
        if not self.save_file_path.exists():
            return [
                DiagnosticResult(
                    name="Save File",
                    status="error",
                    message=f"Save file not found: {self.save_file_path}",
                )
            ]
        results: list[DiagnosticResult] = []
        if not os.access(self.save_file_path, os.R_OK):
            results.append(
                DiagnosticResult(
                    name="Save File Permissions",
                    status="error",
                    message=f"Cannot read the save file {self.save_file_path}",
                    fix_available=True,
                    fix_action="Check the permissions of the save folder.",
                )
            )
        else:
            results.append(
                DiagnosticResult(
                    name="Save File Permissions",
                    status="ok",
                    message=f"Save file is readable: {self.save_file_path}",
                )
            )
        file_size = self.save_file_path.stat().st_size
        if file_size < 1000:
            results.append(
                DiagnosticResult(
                    name="Save File Size",
                    status="error",
                    message=f"Save file suspiciously small ({file_size:,} bytes) - may be corrupted",
                )
            )
        else:
            results.append(
                DiagnosticResult(
                    name="Save File Size",
                    status="ok",
                    message=f"Save file size: {_format_size(file_size)}",
                )
            )
        return results

    def _check_disk_space(self) -> DiagnosticResult | None:
        """Free space on the drives holding the saves and the game."""
        import shutil

        locations: list[tuple[str, Path]] = []
        if self.save_file_path:
            locations.append(("save folder", self.save_file_path.parent))
        elif _is_windows():
            save_root = windows_save_root(self.MANIFEST_KEY)
            if save_root:
                locations.append(("save folder", save_root.parent))
        if self.game_folder:
            locations.append(("game folder", self.game_folder))

        low: list[str] = []
        checked: list[str] = []
        seen_devices: set[int] = set()
        for label, path in locations:
            if not path.exists():
                continue
            device = path.stat().st_dev
            if device in seen_devices:
                continue
            seen_devices.add(device)
            free_gb = shutil.disk_usage(path).free / 1024**3
            entry = f"{label} ({path.anchor or path}): {free_gb:.1f} GB free"
            checked.append(entry)
            if free_gb < 1:
                low.append(entry)
        if not checked:
            return None
        if low:
            return DiagnosticResult(
                name="Low Disk Space",
                status="warning",
                message="Less than 1 GB free. Saving and game updates can fail:",
                bullet_items=low,
                fix_available=True,
                fix_action="Free up space on the listed drive.",
            )
        return DiagnosticResult(
            name="Disk Space",
            status="ok",
            message="Sufficient disk space: " + "; ".join(checked),
        )


# ---------------------------------------------------------------------------
# Game subclasses
# ---------------------------------------------------------------------------


def _find_seamless_coop_artifacts(
    game_dir: Path, prefix: str
) -> tuple[Path | None, Path | None, Path | None]:
    """
    Locate <prefix>.dll, <prefix>_settings.ini, and <prefix>_launcher.exe
    anywhere under game_dir, up to a shallow depth. Seamless Co-op release
    zips extract into a wrapper folder, and a common mistake is copying that
    wrapper into the game folder instead of just its contents, which leaves
    these files nested one or two levels deeper than expected.
    """
    dll_name = f"{prefix}.dll"
    ini_name = f"{prefix}_settings.ini"
    launcher_name = f"{prefix}_launcher.exe"
    max_depth = 3
    dll_path: Path | None = None
    ini_path: Path | None = None
    launcher_path: Path | None = None
    stack: list[tuple[Path, int]] = [(game_dir, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < max_depth:
                    stack.append((entry, depth + 1))
                continue
            name_lower = entry.name.lower()
            if name_lower == dll_name and dll_path is None:
                dll_path = entry
            elif name_lower == ini_name and ini_path is None:
                ini_path = entry
            elif name_lower == launcher_name and launcher_path is None:
                launcher_path = entry
    return dll_path, ini_path, launcher_path


class EldenRingChecker(BaseChecker):
    GAME_NAME = "Elden Ring"
    MANIFEST_KEY = "elden_ring"
    EXE_NAME = "eldenring.exe"
    SAVE_FILE_NAME = "ER0000.sl2"
    GAME_SUBFOLDER = "Game"
    SEAMLESS_COOP_PREFIX = "ersc"
    PIRACY_FOLDERS = ["_CommonRedist", "AdvGuide", "ArtbookOST"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
        "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results = super()._check_extra()
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
            coop_admin = self._check_seamless_coop_launcher_admin_flag()
            if coop_admin:
                results.append(coop_admin)
            results.extend(self._check_seamless_coop())
        return results


class NightReignChecker(BaseChecker):
    GAME_NAME = "Elden Ring Nightreign"
    MANIFEST_KEY = "nightreign"
    EXE_NAME = "nightreign.exe"
    SAVE_FILE_NAME = "NR0000.sl2"
    GAME_SUBFOLDER = "Game"
    SEAMLESS_COOP_PREFIX = "nrsc"
    PIRACY_FOLDERS = ["_CommonRedist", "AdvGuide"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
        "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results = super()._check_extra()
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
            coop_admin = self._check_seamless_coop_launcher_admin_flag()
            if coop_admin:
                results.append(coop_admin)
            results.extend(self._check_seamless_coop())
        return results


class DarkSouls1Checker(BaseChecker):
    GAME_NAME = "Dark Souls Remastered"
    MANIFEST_KEY = "dark_souls_remastered"
    EXE_NAME = "DarkSoulsRemastered.exe"
    SAVE_FILE_NAME = "DRAKS0005.sl2"
    GAME_SUBFOLDER = ""  # flat - files sit directly in install root
    SEAMLESS_COOP_PREFIX = "ds1sc"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results = super()._check_extra()
        if self.game_folder and self.game_folder.exists():
            coop_admin = self._check_seamless_coop_launcher_admin_flag()
            if coop_admin:
                results.append(coop_admin)
            results.extend(self._check_seamless_coop())
        return results


class DarkSouls2Checker(BaseChecker):
    GAME_NAME = "Dark Souls II: Scholar of the First Sin"
    MANIFEST_KEY = "dark_souls_2"
    EXE_NAME = "DarkSoulsII.exe"
    SAVE_FILE_NAME = "DS2SOFS0000.sl2"
    GAME_SUBFOLDER = "Game"
    SEAMLESS_COOP_PREFIX = "ds2sc"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
        "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results = super()._check_extra()
        firewall = self._check_firewall_block()
        if firewall:
            results.append(firewall)
        if self.game_folder and self.game_folder.exists():
            coop_admin = self._check_seamless_coop_launcher_admin_flag()
            if coop_admin:
                results.append(coop_admin)
            results.extend(self._check_seamless_coop())
        return results


class DarkSouls3Checker(BaseChecker):
    GAME_NAME = "Dark Souls III"
    MANIFEST_KEY = "dark_souls_3"
    EXE_NAME = "DarkSoulsIII.exe"
    SAVE_FILE_NAME = "DS30000.sl2"
    GAME_SUBFOLDER = "Game"
    SEAMLESS_COOP_PREFIX = "ds3sc"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
        "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results = super()._check_extra()
        if self.game_folder and self.game_folder.exists():
            coop_admin = self._check_seamless_coop_launcher_admin_flag()
            if coop_admin:
                results.append(coop_admin)
            results.extend(self._check_seamless_coop())
        return results


class SekiroChecker(BaseChecker):
    GAME_NAME = "Sekiro: Shadows Die Twice"
    MANIFEST_KEY = "sekiro"
    EXE_NAME = "sekiro.exe"
    SAVE_FILE_NAME = "S0000.sl2"
    GAME_SUBFOLDER = ""  # flat - files sit directly in install root
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
    ]


class ArmoredCore6Checker(BaseChecker):
    GAME_NAME = "Armored Core VI: Fires of Rubicon"
    MANIFEST_KEY = "armored_core_6"
    EXE_NAME = "armoredcore6.exe"
    SAVE_FILE_NAME = "AC60000.sl2"
    GAME_SUBFOLDER = "Game"
    PIRACY_FOLDERS = ["_CommonRedist"]
    PIRACY_FILES = [
        "dlllist.txt",
        "OnlineFix.ini",
        "OnlineFix64.dll",
        "steam_api64.rne",
        "steam_emu.ini",
        "winmm.dll",
        "dinput8.dll",
    ]

    def _check_extra(self) -> list[DiagnosticResult]:
        results = super()._check_extra()
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
        return results
