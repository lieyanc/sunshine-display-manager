#!/usr/bin/env python3
import json
import os
import shutil
import sys
from pathlib import Path


def is_obsolete_low_res_app(app):
    if app.get("name") != "Low Res Desktop":
        return False
    return app.get("prep-cmd") == [
        {
            "do": "xrandr --output HDMI-1 --mode 1920x1080",
            "undo": "xrandr --output HDMI-1 --mode 1920x1200",
        }
    ]


def main():
    path = Path(sys.argv[1]).expanduser()
    if not path.exists():
        return

    with path.open(encoding="utf-8") as source:
        config = json.load(source)

    apps = config.get("apps", [])
    migrated_apps = [app for app in apps if not is_obsolete_low_res_app(app)]
    if len(migrated_apps) == len(apps):
        return

    backup = path.with_name(f"{path.name}.before-display-manager")
    if not backup.exists():
        shutil.copy2(path, backup)
    config["apps"] = migrated_apps

    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as destination:
        json.dump(config, destination, indent=2)
        destination.write("\n")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
