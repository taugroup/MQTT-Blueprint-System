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
    """Copy src into dst, merging folders and overwriting files."""
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
# plugin discovery
# -----------------------------
def find_installed_engine_plugin(unreal_engine_path: Path, plugin_folder_name: str) -> Path:
    """
    Finds an installed engine plugin folder by searching common locations.
    Returns the folder that contains <plugin_folder_name>.uplugin.
    """
    # Fast-path common locations
    fast_candidates = [
        unreal_engine_path / "Engine" / "Plugins" / "Marketplace" / plugin_folder_name,
        unreal_engine_path / "Engine" / "Plugins" / plugin_folder_name,
    ]
    for c in fast_candidates:
        if (c / f"{plugin_folder_name}.uplugin").exists():
            return c

    # Broader search under Engine/Plugins
    plugins_root = unreal_engine_path / "Engine" / "Plugins"
    if not plugins_root.exists():
        raise FileNotFoundError(f"Engine/Plugins folder not found under: {unreal_engine_path}")

    # Search for the .uplugin file
    for uplugin in plugins_root.rglob(f"{plugin_folder_name}.uplugin"):
        return uplugin.parent

    raise FileNotFoundError(
        f'Installed engine plugin "{plugin_folder_name}" not found under {plugins_root}'
    )


# -----------------------------
# main
# -----------------------------
def main():
    step = "INIT"
    script_dir = Path(__file__).resolve().parent
    control_path = script_dir / "controlPanel.txt"

    created_paths: list[Path] = []

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

        # Enable ONLY the MQTT plugin (seedTemplate-related plugins removed)
        step = "ENABLE_PLUGIN_IN_UPROJECT"
        enable_plugins_in_uproject(uproject, ["MQTT_BP_System_v05_ABStable"])

        # Find installed engine plugin folder
        step = "FIND_ENGINE_PLUGIN"
        engine_plugin_root = find_installed_engine_plugin(unreal_engine_path, "MQTT_BP_System_v05_ABStable")

        # Copy external resource folders into project root
        step = "COPY_RESOURCES_GUIDE_AND_PYTHON"
        resources_dir = engine_plugin_root / "Resources"
        guide_src = resources_dir / "MQTT BP Guide"
        py_src = resources_dir / "MQTT_Python"

        if not resources_dir.exists():
            raise FileNotFoundError(f"Plugin Resources folder not found: {resources_dir}")
        if not guide_src.exists():
            raise FileNotFoundError(f'Expected folder not found in plugin Resources: "{guide_src.name}"')
        if not py_src.exists():
            raise FileNotFoundError(f'Expected folder not found in plugin Resources: "{py_src.name}"')

        guide_dst = unreal_project_path / "MQTT BP Guide"
        py_dst = unreal_project_path / "MQTT_Python"

        # Track only if we create brand new folders (for rollback on failure)
        if not guide_dst.exists():
            created_paths.append(guide_dst)
        if not py_dst.exists():
            created_paths.append(py_dst)

        copytree_merge(guide_src, guide_dst)
        copytree_merge(py_src, py_dst)

        # Success: reset Was_Packaged back to "0" (per setup note)
        step = "RESET_WAS_PACKAGED_FALSE"
        write_control_panel(control_path, {"Was_Packaged": "0"})

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

        msg = f"Step: {step}\n\nException:\n{repr(e)}\n\nTraceback:\n{traceback.format_exc()}"
        write_error_log(script_dir, msg)


if __name__ == "__main__":
    main()
