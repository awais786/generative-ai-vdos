import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.projects.models import Project
from apps.projects.workdir import assemble_is_live


class Command(BaseCommand):
    help = "Remove orphaned workdirs/ trees left by deleted projects or failed assemblies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be removed without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        base = Path(settings.BASE_DIR).parent / "workdirs"

        if not base.exists():
            self.stdout.write("workdirs/ does not exist — nothing to clean.")
            return

        existing_ids = set(Project.objects.values_list("id", flat=True))

        removed_dirs = 0
        freed_bytes = 0

        # workdirs/{owner_id}/{project_id}/
        for owner_dir in sorted(base.iterdir()):
            if not owner_dir.is_dir():
                continue
            for project_dir in sorted(owner_dir.iterdir()):
                if not project_dir.is_dir():
                    continue

                # Remove stale _assemble/ staging dirs; skip live ones (assembly
                # task owns the dir and its finally block will clean it up).
                assemble_dir = project_dir / "_assemble"
                assemble_size = 0
                if assemble_dir.exists():
                    if assemble_is_live(assemble_dir):
                        self.stdout.write(f"  skipping live _assemble/: {assemble_dir}")
                        continue
                    assemble_size = _dir_size(assemble_dir)
                    self.stdout.write(f"  {'[dry-run] ' if dry_run else ''}stale _assemble/: {assemble_dir}  ({_fmt(assemble_size)})")
                    if not dry_run:
                        shutil.rmtree(assemble_dir, ignore_errors=True)
                    removed_dirs += 1
                    freed_bytes += assemble_size

                # Remove the entire project dir if the project no longer exists in DB.
                try:
                    import uuid
                    uuid.UUID(project_dir.name)
                except ValueError:
                    continue

                if project_dir.name not in {str(i) for i in existing_ids}:
                    size = _dir_size(project_dir)
                    # In dry-run, _assemble wasn't actually removed, so subtract its
                    # bytes to avoid double-counting (real run removes it first).
                    if dry_run:
                        size -= assemble_size
                    self.stdout.write(f"  {'[dry-run] ' if dry_run else ''}orphaned project dir: {project_dir}  ({_fmt(size)})")
                    if not dry_run:
                        shutil.rmtree(project_dir, ignore_errors=True)
                    removed_dirs += 1
                    freed_bytes += size

        action = "Would free" if dry_run else "Freed"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{action} {_fmt(freed_bytes)} across {removed_dirs} director{'y' if removed_dirs == 1 else 'ies'}."
            )
        )


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _fmt(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
