# embedPlugin.py
# Builds + installs MQTT_BP_System_v05_ABStable plugin into UE Engine Marketplace using controlPanel.txt

import os
import re
import json
import shutil
import subprocess
import traceback
from pathlib import Path
from datetime import datetime


# -----------------------------
# Helpers: control panel parsing
# -----------------------------
CONTROL_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*:\s*"(.*)"\s*$')

def read_control_panel(txt_path: Path) -> dict:
    data = {}
    raw_lines = txt_path.read_text(encoding="utf-8").splitlines()
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = CONTROL_RE.match(line)
        if m:
            k, v = m.group(1), m.group(2)
            data[k] = v
    return data

def write_control_panel(txt_path: Path, updates: dict) -> None:
    lines = txt_path.read_text(encoding="utf-8").splitlines()
    out = []
    seen = set()

    for line in lines:
        m = CONTROL_RE.match(line.strip())
        if m:
            k = m.group(1)
            if k in updates:
                out.append(f'{k}: "{updates[k]}"')
                seen.add(k)
            else:
                out.append(line)
        else:
            out.append(line)

    # Append keys that didn't exist
    existing_keys = set()
    for l in lines:
        mm = CONTROL_RE.match(l.strip())
        if mm:
            existing_keys.add(mm.group(1))

    for k, v in updates.items():
        if k not in existing_keys:
            out.append(f'{k}: "{v}"')

    txt_path.write_text("\n".join(out) + "\n", encoding="utf-8")


# -----------------------------
# Helpers: logging + rollback
# -----------------------------
def timestamp() -> str:
    # YYYY_MM_DD_HH_XX_SSSS (SSSS = seconds)
    return datetime.now().strftime("%Y_%m_%d_%H_%M_%S")

def write_error_log(script_dir: Path, filename_suffix: str, message: str) -> Path:
    log_name = f"{timestamp()}_ERROR_LOG_{filename_suffix}.txt"
    log_path = script_dir / log_name
    if not message or not message.strip():
        message = "Unknown Error"
    log_path.write_text(message, encoding="utf-8")
    return log_path

def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)

def safe_rm_contents(folder: Path) -> None:
    if not folder.exists():
        return
    for child in folder.iterdir():
        try:
            if child.is_dir():
                safe_rmtree(child)
            else:
                child.unlink()
        except Exception:
            pass


# -----------------------------
# UE helpers
# -----------------------------
def find_uproject(project_dir: Path) -> Path | None:
    if not project_dir.exists():
        return None
    direct = list(project_dir.glob("*.uproject"))
    if direct:
        return direct[0]
    for p in project_dir.rglob("*.uproject"):
        return p
    return None

def is_plugin_enabled_in_uproject(uproject_path: Path, plugin_name: str) -> bool:
    try:
        data = json.loads(uproject_path.read_text(encoding="utf-8"))
        plugins = data.get("Plugins", [])
        for p in plugins:
            if p.get("Name") == plugin_name:
                return bool(p.get("Enabled", False))
        return False
    except Exception:
        return False

def normalize_engine_version(version_str: str) -> str:
    v = version_str.strip()
    if v.count(".") == 1:
        return v + ".0"
    return v

def edit_uplugin_engine_version(uplugin_path: Path, engine_version: str) -> None:
    text = uplugin_path.read_text(encoding="utf-8")

    new_text, n = re.subn(
        r'("EngineVersion"\s*:\s*")([^"]*)(")',
        rf'\g<1>{engine_version}\g<3>',
        text,
        count=1
    )

    if n == 0:
        # Best-effort insert if missing
        if "VersionName" in text:
            new_text = re.sub(
                r'("VersionName"\s*:\s*"[^"]*"\s*,)',
                r'\1\n  "EngineVersion": "' + engine_version + r'",',
                text,
                count=1
            )
        else:
            new_text = text.replace("{", '{\n  "EngineVersion": "' + engine_version + '",', 1)

    uplugin_path.write_text(new_text, encoding="utf-8")

def run_uat_buildplugin(runuat_bat: Path, uplugin_path: Path, package_dir: Path, target_platform: str) -> None:
    cmd = (
        f'"{runuat_bat}" BuildPlugin '
        f'-Plugin="{uplugin_path}" '
        f'-Package="{package_dir}" '
        f'-TargetPlatforms={target_platform} '
        f'-Rocket'
    )

    proc = subprocess.run(
        cmd,
        cwd=str(runuat_bat.parent),
        capture_output=True,
        text=True,
        shell=True
    )

    if proc.stdout:
        print(proc.stdout)

    if proc.returncode != 0:
        err = proc.stderr.strip() if proc.stderr else "Unknown Error"
        raise RuntimeError(f"UAT BuildPlugin failed.\n\nSTDERR:\n{err}\n\nSTDOUT:\n{proc.stdout}")

def find_packaged_plugin_dir(packaged_dir: Path, plugin_uplugin_name: str) -> Path:
    """
    UE's BuildPlugin output may be:
      - <PackageDir>/<PluginName>/<PluginName>.uplugin
      - <PackageDir>/HostProject/Plugins/<PluginName>/<PluginName>.uplugin
      - other nested variants
    We search recursively and return the parent directory of the best match.
    """
    candidates = list(packaged_dir.rglob(plugin_uplugin_name))
    if not candidates:
        stem = Path(plugin_uplugin_name).stem
        candidates = [p for p in packaged_dir.rglob("*.uplugin") if p.stem == stem]

    if not candidates:
        raise FileNotFoundError(f"Packaged plugin .uplugin not found under: {packaged_dir}")

    def score(p: Path) -> tuple:
        parts = [x.lower() for x in p.parts]
        hostproject = 0 if "hostproject" in parts else 1
        plugins = 0 if "plugins" in parts else 1
        depth = len(parts)
        return (hostproject, plugins, depth)

    best = sorted(candidates, key=score)[0]
    return best.parent


# -----------------------------
# Main build/install flow
# -----------------------------
def main():
    step = "INIT"
    script_dir = Path(__file__).resolve().parent

    control_path = script_dir / "controlPanel.txt"
    if not control_path.exists():
        print("Error at READ_CONTROL_PANEL, BUILD FAILED")
        write_error_log(script_dir, "EMBED_PLUGIN", "Missing controlPanel.txt")
        return

    installed_dest: Path | None = None

    try:
        step = "READ_CONTROL_PANEL"
        cfg = read_control_panel(control_path)

        unreal_engine_path = Path(cfg.get("Unreal_Engine_Path", "")).expanduser()
        unreal_engine_version = cfg.get("Unreal_Engine_Version", "")
        sdk_build = cfg.get("SDK_Build", "Win64")
        unreal_project_path = Path(cfg.get("Unreal_Project_Path", "")).expanduser()

        if not unreal_engine_path.exists():
            raise FileNotFoundError(f"Unreal_Engine_Path not found: {unreal_engine_path}")
        if not unreal_project_path.exists():
            raise FileNotFoundError(f"Unreal_Project_Path not found: {unreal_project_path}")

        step = "CHECK_MQTTUTILITIES_ENABLED"
        uproject = find_uproject(unreal_project_path)
        if uproject:
            if not is_plugin_enabled_in_uproject(uproject, "MqttUtilities"):
                print('WARNING: "MqttUtilities" plugin was undetected and the MQTT_BP_System_v05_ABStable may not function properly')
        else:
            print('WARNING: No .uproject found in Unreal_Project_Path; cannot check "MqttUtilities" enable state. Continuing...')

        step = "RESOLVE_PLUGIN_PATHS"
        data_dir = script_dir / "Data"
        plugin_root = data_dir / "MQTT_BP_System_v05_ABStable"
        uplugin_path = plugin_root / "MQTT_BP_System_v05_ABStable.uplugin"
        packaged_dir = data_dir / "packaged"

        if not uplugin_path.exists():
            raise FileNotFoundError(f"Missing .uplugin: {uplugin_path}")

        packaged_dir.mkdir(parents=True, exist_ok=True)

        step = "EDIT_UPLUGIN_ENGINE_VERSION"
        ev = normalize_engine_version(unreal_engine_version)
        edit_uplugin_engine_version(uplugin_path, ev)

        step = "RUN_UAT_BUILDPLUGIN"
        runuat = unreal_engine_path / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
        if not runuat.exists():
            raise FileNotFoundError(f"RunUAT.bat not found: {runuat}")

        # Clean packaged folder before build
        safe_rm_contents(packaged_dir)

        run_uat_buildplugin(runuat, uplugin_path, packaged_dir, sdk_build)

        # -------- FIXED: robust packaged output detection --------
        step = "VERIFY_PACKAGED_OUTPUT"
        built_plugin_dir = find_packaged_plugin_dir(packaged_dir, "MQTT_BP_System_v05_ABStable.uplugin")

        # Install destination: <UE>\Engine\Plugins\Marketplace\MQTT_BP_System_v05_ABStable
        step = "INSTALL_TO_ENGINE_MARKETPLACE"
        marketplace_dir = unreal_engine_path / "Engine" / "Plugins" / "Marketplace"
        marketplace_dir.mkdir(parents=True, exist_ok=True)
        dest_dir = marketplace_dir / "MQTT_BP_System_v05_ABStable"

        if dest_dir.exists():
            safe_rmtree(dest_dir)

        shutil.copytree(built_plugin_dir, dest_dir)
        installed_dest = dest_dir

        step = "UPDATE_WAS_PACKAGED_TRUE"
        write_control_panel(control_path, {"Was_Packaged": "1"})

        step = "CLEAN_PACKAGED_FOLDER"
        safe_rm_contents(packaged_dir)

        print("BUILD SUCCESSFUL")

    except Exception as e:
        print(f"Error at {step}, BUILD FAILED")

        # Rollback install if it happened
        if installed_dest and installed_dest.exists():
            safe_rmtree(installed_dest)

        # Best-effort cleanup packaged contents
        try:
            packaged_dir = script_dir / "Data" / "packaged"
            safe_rm_contents(packaged_dir)
        except Exception:
            pass

        msg = f"Step: {step}\n\nException:\n{repr(e)}\n\nTraceback:\n{traceback.format_exc()}"
        write_error_log(script_dir, "EMBED_PLUGIN", msg)


if __name__ == "__main__":
    main()
