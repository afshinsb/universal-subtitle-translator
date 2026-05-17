from pathlib import Path

from app.config import settings
from app.database import add_log, clear_history


def format_bytes(size: int) -> str:
    value = float(size)

    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(value)} bytes"
            return f"{value:.1f} {unit}"

        value /= 1024

    return f"{value:.1f} GB"


def app_managed_roots() -> list[Path]:
    return [
        settings.upload_dir,
        settings.output_dir,
        settings.temp_dir,
    ]


def safe_cleanup_root(path: Path) -> tuple[Path | None, str | None]:
    data_root = settings.data_dir.resolve()
    root = path.resolve()

    if root == data_root:
        return None, f"Refusing to clean data root directly: {root}"

    if data_root not in root.parents:
        return None, f"Refusing to clean folder outside DATA_DIR: {root}"

    if root.anchor == str(root):
        return None, f"Refusing to clean filesystem root: {root}"

    return root, None


def child_is_inside_root(child: Path, root: Path) -> bool:
    try:
        resolved_child = child.resolve(strict=False)
    except OSError:
        return False

    return resolved_child == root or root in resolved_child.parents


def delete_child(path: Path, root: Path, summary: dict) -> None:
    if not child_is_inside_root(path, root):
        warning = f"Skipped path outside managed root: {path}"
        summary["warnings"].append(warning)
        add_log(level="WARNING", event="cleanup_skipped_path", message=warning)
        return

    try:
        if path.is_symlink():
            size = path.lstat().st_size
            path.unlink()
            summary["files_deleted"] += 1
            summary["bytes_freed"] += size
            add_log(level="INFO", event="cleanup_deleted_file", message=f"Deleted symlink: {path}")
            return

        if path.is_dir():
            for child in path.iterdir():
                delete_child(child, root, summary)

            try:
                path.rmdir()
                summary["folders_deleted"] += 1
                add_log(level="INFO", event="cleanup_deleted_folder", message=f"Deleted folder: {path}")
            except OSError as exc:
                message = f"Could not remove folder {path}: {exc}"
                summary["errors"].append(message)
                add_log(level="ERROR", event="cleanup_error", message=message)
            return

        if path.is_file():
            size = path.stat().st_size
            path.unlink()
            summary["files_deleted"] += 1
            summary["bytes_freed"] += size
            add_log(level="INFO", event="cleanup_deleted_file", message=f"Deleted file: {path}")
            return

        warning = f"Skipped unsupported path type: {path}"
        summary["warnings"].append(warning)
        add_log(level="WARNING", event="cleanup_skipped_path", message=warning)
    except OSError as exc:
        message = f"Could not delete {path}: {exc}"
        summary["errors"].append(message)
        add_log(level="ERROR", event="cleanup_error", message=message)


def clean_app_folder(root: Path, summary: dict) -> None:
    safe_root, warning = safe_cleanup_root(root)

    if warning:
        summary["warnings"].append(warning)
        add_log(level="WARNING", event="cleanup_skipped_root", message=warning)
        return

    if not safe_root:
        return

    safe_root.mkdir(parents=True, exist_ok=True)

    for child in safe_root.iterdir():
        delete_child(child, safe_root, summary)

    summary["folders_cleaned"] += 1
    add_log(level="INFO", event="cleanup_cleaned_folder", message=f"Cleaned app folder: {safe_root}")


def cleanup_history_and_app_files() -> dict:
    summary = {
        "files_deleted": 0,
        "folders_deleted": 0,
        "folders_cleaned": 0,
        "bytes_freed": 0,
        "bytes_freed_display": "0 bytes",
        "errors": [],
        "warnings": [],
        "history": {
            "jobs": 0,
            "batches": 0,
            "logs": 0,
        },
        "external_media_touched": False,
    }

    history = clear_history()
    summary["history"] = history

    add_log(
        level="INFO",
        event="cleanup_history_cleared",
        message=(
            f"Cleared history. Jobs: {history['jobs']}, "
            f"Batches: {history['batches']}, Logs: {history['logs']}."
        ),
    )

    for root in app_managed_roots():
        clean_app_folder(root, summary)

    summary["bytes_freed_display"] = format_bytes(summary["bytes_freed"])

    add_log(
        level="SUCCESS" if not summary["errors"] else "WARNING",
        event="cleanup_completed",
        message=(
            f"Cleanup completed. Files deleted: {summary['files_deleted']}. "
            f"Folders cleaned: {summary['folders_cleaned']}. "
            f"Freed: {summary['bytes_freed_display']}. "
            "External media folders were not touched."
        ),
    )

    return summary
