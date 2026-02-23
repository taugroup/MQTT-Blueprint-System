import os
import re
import json
import shutil
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

CONTROL_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*:\s*"(.*)"\s*$')


# -----------------------------
# controlPanel helpers
# -----------------------------
def read_control_panel(txt_path: Path) -> dict:
    data = {}
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = CONTROL_RE.match(s)
        if m:
            data[m.group(1)] = m.group(2)
    return data


def write_control_panel(txt_path: Path, updates: dict) -> None:
    lines = txt_path.read_text(encoding="utf-8").splitlines()
    out = []
    existing_keys = set()

    for line in lines:
        m = CONTROL_RE.match(line.strip())
        if m:
            k = m.group(1)
            existing_keys.add(k)
            if k in updates:
                out.append(f'{k}: "{updates[k]}"')
            else:
                out.append(line)
        else:
            out.append(line)

    for k, v in updates.items():
        if k not in existing_keys:
            out.append(f'{k}: "{v}"')

    txt_path.write_text("\n".join(out) + "\n", encoding="utf-8")


# -----------------------------
# logging + rollback helpers
# -----------------------------
def timestamp() -> str:
    return datetime.now().strftime("%Y_%m_%d_%H_%M_%S")


def write_error_log(script_dir: Path, message: str) -> Path:
    log_path = script_dir / f"{timestamp()}_ERROR_LOG_ENABLE_TEMPLATE.txt"
    if not message.strip():
        message = "Unknown Error"
    log_path.write_text(message, encoding="utf-8")
    return log_path


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def copytree_merge(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_root = dst / rel
        target_root.mkdir(parents=True, exist_ok=True)
        for d in dirs:
            (target_root / d).mkdir(parents=True, exist_ok=True)
        for f in files:
            s = Path(root) / f
            t = target_root / f
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, t)


# -----------------------------
# uproject helpers
# -----------------------------
def find_uproject(project_dir: Path) -> Path | None:
    direct = list(project_dir.glob("*.uproject"))
    if direct:
        return direct[0]
    for p in project_dir.rglob("*.uproject"):
        return p
    return None


def enable_plugins_in_uproject(uproject_path: Path, plugin_names: list[str]) -> None:
    data = json.loads(uproject_path.read_text(encoding="utf-8"))
    plugins = data.get("Plugins")
    if plugins is None:
        plugins = []
        data["Plugins"] = plugins

    for name in plugin_names:
        found = False
        for p in plugins:
            if p.get("Name") == name:
                p["Enabled"] = True
                found = True
                break
        if not found:
            plugins.append({"Name": name, "Enabled": True})

    uproject_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -----------------------------
# Unreal runner
# -----------------------------
def find_editor_exe(unreal_engine_path: Path) -> Path:
    candidates = [
        unreal_engine_path / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe",
        unreal_engine_path / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe",
        unreal_engine_path / "Engine" / "Binaries" / "Win64" / "UE4Editor.exe",
        unreal_engine_path / "Engine" / "Binaries" / "Win64" / "UE4Editor-Cmd.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Could not find UnrealEditor(.exe) under Engine/Binaries/Win64")


def run_unreal_python(unreal_engine_path: Path, uproject_path: Path, py_script: Path, script_dir: Path) -> None:
    editor_exe = find_editor_exe(unreal_engine_path)
    unreal_log = script_dir / f"{timestamp()}_UNREAL_SEED_LOG.txt"

    # Use list args (less quoting pain on Windows)
    args = [
        str(editor_exe),
        str(uproject_path),
        "-AllPlugins",
        "-stdout",
        "-FullStdOutLogOutput",
        "-run=pythonscript",
        f'-script="{str(py_script)}"',
        "-unattended",
        "-nop4",
        "-nosplash",
        f'-log="{str(unreal_log)}"',
    ]

    # shell=True helps Unreal parse -script="..."
    proc = subprocess.run(" ".join(args), capture_output=True, text=True, shell=True)

    if proc.returncode != 0:
        log_text = ""
        if unreal_log.exists():
            log_text = unreal_log.read_text(encoding="utf-8", errors="ignore")
        raise RuntimeError(
            "Unreal python run failed.\n\n"
            f"COMMAND:\n{' '.join(args)}\n\n"
            f"STDOUT:\n{proc.stdout}\n\n"
            f"STDERR:\n{proc.stderr}\n\n"
            f"UNREAL LOG:\n{log_text}\n"
        )


def verify_seeded(project_content_dir: Path) -> bool:
    if not project_content_dir.exists():
        return False
    # We expect /Content/MQTT/... uassets on disk after seeding
    mqtt_dir = project_content_dir / "MQTT"
    if mqtt_dir.exists():
        for p in mqtt_dir.rglob("*.uasset"):
            return True
    # fallback: any mqtt-named asset anywhere
    for p in project_content_dir.rglob("*.uasset"):
        if "mqtt" in p.name.lower():
            return True
    return False


# -----------------------------
# Generate Unreal seeding script (runs inside Unreal)
# -----------------------------
def write_unreal_seed_script(tmp_path: Path) -> None:
    """
    This script runs INSIDE Unreal Editor (headless) and duplicates plugin assets into /Game/MQTT
    so references stay consistent (same behavior as Content Browser "Migrate", but automated).
    """
    script = r'''
import unreal
import sys

PLUGIN_NAME = "MQTT_blueprint_system"
DEST_ROOT = "/Game/MQTT"

def log(msg):
    unreal.log("[MQTT Seed] " + str(msg))

def fail(msg):
    unreal.log_error("[MQTT Seed] " + str(msg))
    raise RuntimeError(msg)

def ensure_dir(path):
    if not unreal.EditorAssetLibrary.does_directory_exist(path):
        unreal.EditorAssetLibrary.make_directory(path)

def list_assets_safe(root):
    try:
        # recursive=True, include_folder=False
        return unreal.EditorAssetLibrary.list_assets(root, recursive=True, include_folder=False)
    except Exception:
        return []

def pick_source_root():
    # Common plugin mount patterns
    candidates = [
        f"/{PLUGIN_NAME}/MQTT",
        f"/{PLUGIN_NAME}",
        "/Plugins/" + PLUGIN_NAME + "/MQTT",     # usually NOT a valid mount, but kept as last-resort
        "/Plugins/" + PLUGIN_NAME,
    ]

    for c in candidates:
        assets = list_assets_safe(c)
        if assets:
            return c, assets

    # If we get here, plugin probably didn't mount in this commandlet session
    fail("Could not find any assets under expected plugin mount paths. "
         "Make sure the plugin is enabled in the .uproject and that the plugin contains Content/MQTT assets.")

def relative_under_root(asset_path, root):
    # asset_path like "/MQTT_blueprint_system/MQTT/Foo/Bar.Bar"
    # root like "/MQTT_blueprint_system/MQTT"
    if asset_path.startswith(root + "/"):
        return asset_path[len(root) + 1:]
    if asset_path == root:
        return ""
    # fallback: strip first 2 segments
    parts = asset_path.strip("/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[2:])
    return asset_path.strip("/")

def to_dest_package(asset_path, root):
    rel = relative_under_root(asset_path, root)
    # remove ".AssetName" object suffix
    pkg = asset_path.split(".")[0]
    # rel package path without suffix
    rel_pkg = rel.split(".")[0]
    return f"{DEST_ROOT}/{rel_pkg}"

def duplicate_assets(src_root, assets):
    ensure_dir(DEST_ROOT)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    duplicated = 0

    for a in assets:
        # skip redirectors
        if a.endswith("_Redirector") or a.lower().endswith("redirector"):
            continue

        src_pkg = a.split(".")[0]
        dest_pkg = to_dest_package(a, src_root)

        # If it already exists, overwrite by delete+dup
        if unreal.EditorAssetLibrary.does_asset_exist(dest_pkg):
            unreal.EditorAssetLibrary.delete_asset(dest_pkg)

        # Make sure destination folder exists
        dest_folder = "/".join(dest_pkg.split("/")[:-1])
        ensure_dir(dest_folder)

        src_asset = unreal.EditorAssetLibrary.load_asset(src_pkg)
        if not src_asset:
            # If load failed, try loading with full object path
            src_asset = unreal.EditorAssetLibrary.load_asset(a)
        if not src_asset:
            fail(f"Failed to load source asset: {a}")

        name = dest_pkg.split("/")[-1]
        dup = asset_tools.duplicate_asset(name, dest_folder, src_asset)
        if not dup:
            fail(f"Failed to duplicate asset: {a} -> {dest_pkg}")

        duplicated += 1

    return duplicated

def fix_redirectors_and_save():
    # Fix redirectors under /Game/MQTT
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    redirectors = unreal.EditorAssetLibrary.list_assets(DEST_ROOT, recursive=True, include_folder=False)
    redirector_assets = []
    for p in redirectors:
        if p.endswith("_Redirector") or p.lower().endswith("redirector"):
            obj = unreal.EditorAssetLibrary.load_asset(p.split(".")[0])
            if obj:
                redirector_assets.append(obj)
    if redirector_assets:
        asset_tools.fixup_redirectors(redirector_assets)

    # Save all under /Game/MQTT
    unreal.EditorAssetLibrary.save_directory(DEST_ROOT, only_if_is_dirty=False, recursive=True)

def main():
    log("Starting seeding into " + DEST_ROOT)

    src_root, assets = pick_source_root()
    log("Source root: " + src_root)
    log("Found assets: " + str(len(assets)))

    count = duplicate_assets(src_root, assets)
    log("Duplicated assets: " + str(count))

    fix_redirectors_and_save()
    log("Done.")

if __name__ == "__main__":
    main()
'''
    tmp_path.write_text(script.strip() + "\n", encoding="utf-8")


# -----------------------------
# main
# -----------------------------
def main():
    step = "INIT"
    script_dir = Path(__file__).resolve().parent
    control_path = script_dir / "controlPanel.txt"

    created_paths: list[Path] = []
    tmp_unreal_script: Path | None = None

    try:
        step = "READ_CONTROL_PANEL"
        if not control_path.exists():
            raise FileNotFoundError("Missing controlPanel.txt")

        cfg = read_control_panel(control_path)
        unreal_engine_path = Path(cfg.get("Unreal_Engine_Path", "")).expanduser()
        unreal_project_path = Path(cfg.get("Unreal_Project_Path", "")).expanduser()
        was_packaged = cfg.get("Was_Packaged", "0").strip()

        if not unreal_engine_path.exists():
            raise FileNotFoundError(f"Unreal_Engine_Path not found: {unreal_engine_path}")
        if not unreal_project_path.exists():
            raise FileNotFoundError(f"Unreal_Project_Path not found: {unreal_project_path}")

        # If Was_Packaged is 0, prompt and possibly run runEmbed.bat
        step = "PROMPT_WAS_ALREADY_PACKAGED"
        if was_packaged == "0":
            ans = input('Was the plugin already packaged "Y" or "N": ').strip().upper()
            if ans not in ("Y", "N"):
                raise ValueError('Invalid response. Enter "Y" or "N".')

            if ans == "N":
                step = "RUN_RUNEMBED_BAT"
                run_embed = script_dir / "runEmbed.bat"
                if not run_embed.exists():
                    raise FileNotFoundError(f"runEmbed.bat not found: {run_embed}")

                proc = subprocess.run(f'"{run_embed}"', cwd=str(script_dir), shell=True)
                if proc.returncode != 0:
                    raise RuntimeError("runEmbed.bat failed (non-zero exit code).")

                write_control_panel(control_path, {"Was_Packaged": "1"})
            else:
                write_control_panel(control_path, {"Was_Packaged": "1"})

        # Re-read after possible update
        cfg = read_control_panel(control_path)
        unreal_engine_path = Path(cfg.get("Unreal_Engine_Path", "")).expanduser()
        unreal_project_path = Path(cfg.get("Unreal_Project_Path", "")).expanduser()

        step = "FIND_UPROJECT"
        uproject = find_uproject(unreal_project_path)
        if not uproject:
            raise FileNotFoundError(f"No .uproject found in: {unreal_project_path}")

        # Enable plugin + editor python deps
        step = "ENABLE_REQUIRED_PLUGINS_IN_UPROJECT"
        enable_plugins_in_uproject(
            uproject,
            [
                "MQTT_blueprint_system",
                "PythonScriptPlugin",
                "EditorScriptingUtilities",
            ],
        )

        # Verify engine plugin exists
        step = "VERIFY_ENGINE_PLUGIN_EXISTS"
        engine_plugin_root = unreal_engine_path / "Engine" / "Plugins" / "Marketplace" / "MQTT_blueprint_system"
        if not engine_plugin_root.exists():
            raise FileNotFoundError(f"Installed engine plugin not found: {engine_plugin_root}")

        # Copy external resource folders into project root
        step = "COPY_RESOURCES_GUIDE_AND_PYTHON"
        resources_dir = engine_plugin_root / "Resources"
        guide_src = resources_dir / "MQTT BP Guide"
        py_src = resources_dir / "MQTT_Python"

        guide_dst = unreal_project_path / "MQTT BP Guide"
        py_dst = unreal_project_path / "MQTT_Python"

        if not guide_dst.exists():
            created_paths.append(guide_dst)
        if not py_dst.exists():
            created_paths.append(py_dst)

        copytree_merge(guide_src, guide_dst)
        copytree_merge(py_src, py_dst)

        # Run the Unreal seeding process (duplicate plugin assets to /Game/MQTT)
        step = "RUN_UNREAL_SEED_TEMPLATE"
        tmp_unreal_script = script_dir / f"__tmp_seed_mqtt_{timestamp()}.py"
        write_unreal_seed_script(tmp_unreal_script)
        created_paths.append(tmp_unreal_script)

        run_unreal_python(unreal_engine_path, uproject, tmp_unreal_script, script_dir)

        # Verify on disk
        step = "VERIFY_SEEDED_CONTENT_ON_DISK"
        project_content_dir = unreal_project_path / "Content"
        if not verify_seeded(project_content_dir):
            raise RuntimeError(
                f"Seed reported success but no MQTT assets were found under: {project_content_dir}\\MQTT"
            )

        # Success: reset Was_Packaged back to "0"
        step = "RESET_WAS_PACKAGED_FALSE"
        write_control_panel(control_path, {"Was_Packaged": "0"})

        # Cleanup temp script
        step = "CLEANUP_TEMP"
        if tmp_unreal_script and tmp_unreal_script.exists():
            tmp_unreal_script.unlink(missing_ok=True)

        print("BUILD SUCCESSFUL")

    except Exception as e:
        print(f"Error at {step}, BUILD FAILED")

        # Rollback created paths (best effort)
        for p in reversed(created_paths):
            try:
                if p.is_dir():
                    safe_rmtree(p)
                elif p.exists():
                    p.unlink()
            except Exception:
                pass

        # NOTE: we do NOT delete /Content/MQTT on failure automatically,
        # because Unreal may have partially duplicated assets and you might want to inspect.
        # If you want hard rollback, tell me and I'll add a safe delete of Content/MQTT.

        msg = f"Step: {step}\n\nException:\n{repr(e)}\n\nTraceback:\n{traceback.format_exc()}"
        write_error_log(script_dir, msg)


if __name__ == "__main__":
    main()
