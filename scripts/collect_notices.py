"""Collect installed package license notices for the exact locked development environment."""
import importlib.metadata
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "licenses"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        notices = []
        for file in dist.files or []:
            if (file.name.lower().startswith(("license", "notice", "copying", "model_licenses")) or "/licenses/" in str(file).replace("\\", "/").lower()) and file.name != "METADATA":
                source = Path(dist.locate_file(file))
                if source.is_file():
                    # Flatten only within a package-specific directory, keeping filename collisions distinct.
                    relative = Path(*file.parts[1:]) if ".dist-info" in file.parts[0] else Path(*file.parts)
                    target = OUTPUT / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source,target)
                    notices.append(str(target.relative_to(ROOT)).replace("\\","/"))
        rows.append({"name":name,"version":dist.version,"license":dist.metadata.get("License-Expression") or dist.metadata.get("License") or ", ".join(dist.metadata.get_all("Classifier",[])),"notices":notices})
    node_root = ROOT / "frontend" / "node_modules"
    for metadata_path in sorted(node_root.glob("*/package.json")) + sorted(node_root.glob("@*/*/package.json")):
        package = json.loads(metadata_path.read_text(encoding="utf-8"))
        name = package.get("name",metadata_path.parent.name)
        notices = []
        for source in metadata_path.parent.iterdir():
            if source.is_file() and source.name.lower().startswith(("license","notice","copying")):
                target = OUTPUT / "npm" / name.replace("/","_") / source.name
                target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,target)
                notices.append(str(target.relative_to(ROOT)).replace("\\","/"))
        rows.append({"name":name,"version":package.get("version"),"license":package.get("license"),"notices":notices})
    (ROOT/"docs"/"dependencies.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Collected license metadata and notices for {len(rows)} Python/npm packages.")


if __name__ == "__main__": main()
