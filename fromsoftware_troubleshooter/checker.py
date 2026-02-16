"""Standalone checker — no er_save_manager dependency."""

import json
import os
import platform
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiagnosticResult:
    name: str
    status: str  # 'ok', 'warning', 'error', 'info'
    message: str
    fix_available: bool = False
    fix_action: str = ""


MANIFEST_URL = (
    "https://raw.githubusercontent.com/Hapfel1/er-save-manager/main/game_file_sizes.json"
)
_MANIFEST_CACHE: dict | None = None


def _load_manifest() -> dict:
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None:
        return _MANIFEST_CACHE
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=3) as resp:
            _MANIFEST_CACHE = json.loads(resp.read().decode())
            return _MANIFEST_CACHE
    except Exception:
        pass
    local = Path(__file__).with_name("game_file_sizes.json")
    if local.exists():
        try:
            _MANIFEST_CACHE = json.loads(local.read_text())
            return _MANIFEST_CACHE
        except Exception:
            pass
    return {}


def _get_size_range(game_key: str, file_key: str) -> tuple[int, int] | None:
    entry = _load_manifest().get(game_key, {}).get(file_key)
    if entry and "min_kb" in entry and "max_kb" in entry:
        return entry["min_kb"], entry["max_kb"]
    return None


def _is_windows() -> bool:
    return platform.system() == "Windows"


PROBLEMATIC_PROCESSES = [
    "vgtray.exe", "Overwolf.exe", "RTSS.exe", "RTSSHooksLoader64.exe",
    "SystemExplorer.exe", "MSIAfterburner.exe", "Medal.exe", "SignalRgb.exe",
    "Discord.exe", "GeForceExperience.exe", "ProcessLasso.exe",
]

VPN_PROCESSES = [
    "NordVPN.exe", "nordvpn-service.exe", "expressvpn.exe", "expressvpnd.exe",
    "surfshark.exe", "SurfsharkService.exe", "protonvpn.exe", "ProtonVPN.exe",
    "CyberGhost.exe", "CG7Service.exe", "pia-client.exe", "pia-service.exe",
    "windscribe.exe", "windscribeservice.exe", "TunnelBear.exe",
    "TunnelBearService.exe", "hsscp.exe", "IPVanish.exe", "AtlasVPN.exe",
    "Cloudflare WARP.exe", "warp-svc.exe", "hamachi-2.exe", "hamachi-2-ui.exe",
    "Radmin VPN.exe", "RvpnService.exe",
]


class BaseChecker:
    GAME_NAME: str = ""
    MANIFEST_KEY: str = ""
    EXE_NAME: str = ""
    SAVE_FILE_NAME: str = ""
    # Subfolder containing the exe and dll — override to "" for flat layouts (DSR)
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
        if not self.game_folder:
            return None
        if self.GAME_SUBFOLDER:
            return self.game_folder / self.GAME_SUBFOLDER
        return self.game_folder

    def run_all_checks(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
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
                message=f"{self.EXE_NAME} not found",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        size_kb = exe_path.stat().st_size // 1024
        size_mb = size_kb / 1024
        size_range = _get_size_range(self.MANIFEST_KEY, "exe")
        if size_range:
            min_kb, max_kb = size_range
            if min_kb <= size_kb <= max_kb:
                return DiagnosticResult(
                    name="Game Executable", status="ok",
                    message=f"{self.EXE_NAME} found ({size_mb:.1f} MB)",
                )
            return DiagnosticResult(
                name="Game Executable", status="warning",
                message=f"{self.EXE_NAME} size is unusual ({size_mb:.1f} MB)",
                fix_available=True,
                fix_action=f"Verify game integrity via Steam: Right-click {self.GAME_NAME} > Properties > Installed Files > Verify",
            )
        return DiagnosticResult(
            name="Game Executable", status="info",
            message=f"{self.EXE_NAME} found ({size_mb:.1f} MB, size manifest unavailable)",
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
                message=f"Found unsupported folders: {', '.join(found_folders)}.",
            ))

        found_files: list[str] = []
        for f in self.PIRACY_FILES:
            if (game_dir / f).exists():
                found_files.append(f)

        steam_api = game_dir / "steam_api64.dll"
        if steam_api.exists():
            size_kb = steam_api.stat().st_size // 1024
            size_range = _get_size_range(self.MANIFEST_KEY, "steam_api64.dll") or (258, 266)
            if not (size_range[0] <= size_kb <= size_range[1]):
                found_files.append(f"steam_api64.dll (modified — {size_kb} KiB)")
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
                message=f"Found unsupported files: {', '.join(found_files)}.",
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
        size_kb = regulation.stat().st_size // 1024
        size_mb = size_kb / 1024
        size_range = _get_size_range(self.MANIFEST_KEY, "regulation.bin")
        if size_range:
            min_kb, max_kb = size_range
            if min_kb <= size_kb <= max_kb:
                return DiagnosticResult(
                    name="Regulation File", status="ok",
                    message=f"regulation.bin is valid ({size_mb:.1f} MB)",
                )
            return DiagnosticResult(
                name="Regulation File", status="warning",
                message=f"regulation.bin size is unusual ({size_mb:.1f} MB). May indicate modified game files.",
                fix_available=True,
                fix_action="Delete the file and verify game integrity via Steam.",
            )
        return DiagnosticResult(
            name="Regulation File", status="info",
            message=f"regulation.bin found ({size_mb:.1f} MB, size manifest unavailable)",
        )

    def _check_problematic_processes(self) -> list[DiagnosticResult]:
        if not _is_windows():
            return [DiagnosticResult(
                name="Process Check", status="info",
                message="Process checking only available on Windows",
            )]
        try:
            output = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"], text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            running = [p for p in PROBLEMATIC_PROCESSES if p.lower() in output.lower()]

            process_lasso_scheduled = False
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
                results.append(DiagnosticResult(
                    name="Problematic Processes Running", status="warning",
                    message=f"Found processes that can cause crashes: {', '.join(running)}",
                    fix_available=True,
                    fix_action="Close these apps before playing, and disable them in Task Manager > Startup tab.",
                ))
            if any("ProcessLasso" in p for p in running) or process_lasso_scheduled:
                results.append(DiagnosticResult(
                    name="Process Lasso Detected", status="error",
                    message="Process Lasso can cause flashbang crashes on launch.",
                    fix_available=True,
                    fix_action="1. Close Process Lasso if running\n2. Disable in Task Manager > Startup tab\n3. Remove from Task Scheduler > Task Scheduler Library",
                ))
            if not running and not process_lasso_scheduled:
                results.append(DiagnosticResult(
                    name="Process Check", status="ok",
                    message="No problematic processes detected",
                ))
            return results
        except Exception as e:
            return [DiagnosticResult(
                name="Process Check", status="warning",
                message=f"Could not check processes: {e}",
            )]

    def _check_vpn_processes(self) -> list[DiagnosticResult]:
        if not _is_windows():
            return [DiagnosticResult(
                name="VPN Check", status="info",
                message="VPN checking only available on Windows",
            )]
        try:
            output = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"], text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            seen: set[str] = set()
            running_vpns = []
            for proc in VPN_PROCESSES:
                if proc.lower() in output.lower():
                    base = proc.replace(".exe", "").split("-")[0]
                    if base not in seen:
                        seen.add(base)
                        running_vpns.append(proc)
            if running_vpns:
                return [DiagnosticResult(
                    name="VPN Detected", status="warning",
                    message=f"Running VPN client(s): {', '.join(running_vpns)}. May cause multiplayer issues.",
                    fix_available=True,
                    fix_action="Disable or exit your VPN before playing online.",
                )]
            return [DiagnosticResult(
                name="VPN Check", status="ok", message="No VPN clients detected"
            )]
        except Exception as e:
            return [DiagnosticResult(
                name="VPN Check", status="warning",
                message=f"Could not check for VPN processes: {e}",
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
                appdata_path = Path(os.getenv("APPDATA", "")) / self.GAME_NAME
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
                message=f"Save file suspiciously small ({file_size} bytes) — may be corrupted",
            ))
        else:
            results.append(DiagnosticResult(
                name="Save File Size", status="ok",
                message=f"Save file size is normal ({file_size // 1024} KB)",
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
    GAME_SUBFOLDER = ""  # flat layout
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

    def _check_extra(self) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []
        if self.game_folder and self.game_folder.exists():
            results.append(self._check_regulation_bin())
        return results