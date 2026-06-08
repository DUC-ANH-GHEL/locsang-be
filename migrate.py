import os
import shutil
from pathlib import Path

def migrate_files():
    # Define paths
    base_path = Path("app")
    old_paths = {
        "api": base_path / "api",
        "models": base_path / "models",
        "repositories": base_path / "repositories",
        "services": base_path / "services",
        "dto": base_path / "dto",
        "dependencies": base_path / "dependencies",
        "db": base_path / "db"
    }

    new_paths = {
        "api": base_path / "presentation" / "api",
        "models": base_path / "domain" / "models",
        "repositories": base_path / "infrastructure" / "repositories",
        "services": base_path / "application" / "services",
        "dto": base_path / "application" / "dto",
        "dependencies": base_path / "core" / "deps",
        "db": base_path / "core" / "database"
    }

    # Create new directories if they don't exist
    for path in new_paths.values():
        path.mkdir(parents=True, exist_ok=True)

    # Move files
    for old_key, old_path in old_paths.items():
        if old_path.exists():
            new_path = new_paths[old_key]
            if old_path.is_dir():
                # Move all files from old directory to new directory
                for item in old_path.glob("**/*"):
                    if item.is_file():
                        rel_path = item.relative_to(old_path)
                        new_item = new_path / rel_path
                        new_item.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(item), str(new_item))
            else:
                # Move single file
                shutil.move(str(old_path), str(new_path))

    # Remove old directories
    for old_path in old_paths.values():
        if old_path.exists():
            if old_path.is_dir():
                shutil.rmtree(old_path)
            else:
                old_path.unlink()

if __name__ == "__main__":
    migrate_files()
