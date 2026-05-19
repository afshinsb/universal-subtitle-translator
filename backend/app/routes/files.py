from fastapi import APIRouter
from app.config import settings

router = APIRouter(prefix="/files")


def output_files(limit: int | None = None) -> list[dict]:
    if not settings.output_dir.exists():
        return []

    files = []

    for path in settings.output_dir.glob("*"):
        if path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue

            files.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )

    files = sorted(files, key=lambda item: item["modified"], reverse=True)

    if limit is not None:
        return files[:limit]

    return files


@router.get("/uploads")
def list_uploads():
    if not settings.upload_dir.exists():
        return {"uploads": []}

    files = []

    for path in settings.upload_dir.rglob("*"):
        if path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                continue

            relative_path = path.relative_to(settings.upload_dir)
            job_id = relative_path.parts[0] if len(relative_path.parts) > 1 else None

            files.append(
                {
                    "name": path.name,
                    "relative_path": str(relative_path),
                    "job_id": job_id,
                    "size": size,
                }
            )

    return {"uploads": sorted(files, key=lambda item: item["relative_path"])}


@router.get("/outputs")
def list_outputs():
    return {"outputs": output_files()}
