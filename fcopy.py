from typing import Self
from pathlib import Path
import shutil
from fnmatch import fnmatch
import time
from collections import Counter
from rich.progress import track

from rich.logging import RichHandler
import logging
logging.basicConfig(
    level = "INFO",
    format = "%(message)s",
    handlers = [RichHandler(rich_tracebacks=True)]
)
log = logging.getLogger("rich")

def _format_execution_time(delta_time: float) -> str:
    if delta_time < 1:
        return f"{int(delta_time * 1000)} ms"
    
    if delta_time < 60:
        return f"{int(delta_time)}s"
    
    if delta_time < 3600:
        m, s = divmod(delta_time, 60)
        return f"{int(m)}M {int(s)}s"
    
    h, m = divmod(delta_time, 3600)
    return f"{int(h)}H {int(m/60)}M"

def _timed(phase_name: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            st = time.time()
            
            result = func(*args, **kwargs)
            
            et = time.time()
            log.info(f"{phase_name} [bold green blink]SUCCESSFUL[/] in [bold cyan blink]{_format_execution_time(et - st)}[/]", extra={"markup": True})

            return result
        return wrapper
    return decorator

class Task:
    def __init__(self):
        self.task_count: int = 0
        self.src_list: list[Path] = []
        self.dst_list: list[Path] = []
        self.pat_include: list[list[str]] = []
        self.pat_exclude: list[list[str]] = []
        
        self.pre_directories: list[Path] = []
        self.pre_file_src: list[Path] = []
        self.pre_file_dst: list[Path] = []
        
    def add(self, src_path: str, dst_path: str, pat_include: list[str] = [], pat_exclude: list[str] = []) -> Self:
        """
        Add a task to copy either a file or a directory. Note that destination must be a directory.
        """
        
        src, dst = Path(src_path), Path(dst_path)
        
        if not src.exists():
            log.warning(f"Source {src_path} does not exist. Skipping...")
            return self
        
        if dst.exists():
            log.warning(f"Destination {dst_path} already exists. Skipping...")
            return self
        
        if not src.is_absolute():
            log.warning(f"Source {src_path} is not absolute.")
        
        if not dst.is_absolute():
            log.warning(f"Destination {dst_path} is not absolute.")
        
        self.src_list.append(src)
        self.dst_list.append(dst)
        self.pat_include.append(pat_include)
        self.pat_exclude.append(pat_exclude)
        self.task_count += 1
        return self
        
    @_timed("Preparation")
    def prepare(self) -> Self:
        """
        Prepare for the execution, generating all the directory/file info.
        """
        
        log.info("\n==================== Preparation Phase ====================")
        
        for i in range(self.task_count):
            src_root, dst, inc, exc = self.src_list[i], self.dst_list[i], self.pat_include[i], self.pat_exclude[i]
            
            queue: list[Path] = [src_root]
            while queue:
                src = queue.pop().absolute()
                
                if self._should_exclude(src, exc):
                    log.info(f"Excluded {src}")
                    continue
                
                if src.is_dir():
                    queue += list(src.iterdir())
                    self._add_pre_dir(dst / src.relative_to(src_root))
                    continue
                
                # src is a file
                pre_dir = dst / src.relative_to(src_root).parent
                pre_dst = pre_dir / src.name                
                self._add_pre_dir(pre_dir)
                self._add_pre_file(src, pre_dst)
                continue

        return self

    __DEFAULT_EXCLUDE_FILE_PATTERNS = [
        "~*",
        "*.tmp",
        "Thumbs.db",    # Windows thumbnail cache
        ".DS_Store",    # macOS Finder metadata
        ".git",
        "__pycache__"
    ]
    def _should_exclude(self, path: Path, pat_exclude: list[str]) -> bool:
        return (
            any(fnmatch(path.name, pattern) for pattern in self.__DEFAULT_EXCLUDE_FILE_PATTERNS)
            or
            any(fnmatch(path.name, pattern) for pattern in pat_exclude)
        )
    
    def _add_pre_dir(self, pre_dir: Path) -> None:
        if pre_dir not in self.pre_directories:
            self.pre_directories.append(pre_dir)
    
    def _add_pre_file(self, pre_file_src: Path, pre_file_dst: Path) -> None:
        self.pre_file_src.append(pre_file_src)
        self.pre_file_dst.append(pre_file_dst)
        
    @_timed("Validation")
    def validate(self) -> Self:
        """
        Check for conflicts or overwrites. If there are, raise an error.
        """
        
        log.info("\n==================== Validation Phase ====================")
        
        assert self.task_count > 0, "No tasks to execute."
        
        for i in range(self.task_count):
            src, dst = self.src_list[i], self.dst_list[i]
            for j in range(i + 1, self.task_count):
                assert src != self.src_list[j], f"Duplicate source {src}"
                assert dst != self.dst_list[j], f"Duplicate destination {dst}"
                
                assert not src.is_relative_to(self.src_list[j]), f"Source {self.src_list[j]} is the parent of {src}"
                assert not self.src_list[j].is_relative_to(src), f"Source {src} is the parent of {self.src_list[j]}"
        
        for d in self.pre_directories:
            assert d.is_absolute(), f"Pre-generated destination directory {d} is not absolute."
            assert not d.exists(), f"Pre-generated destination directory {d} already exists."
        
        for f in self.pre_file_src:
            assert f.is_absolute(), f"Pre-generated source file {f} is not absolute."
            assert f.exists(), f"Pre-generated source file {f} does not exist."
        
        for f in self.pre_file_dst:
            assert f.is_absolute(), f"Pre-generated destination file {f} is not absolute."
            assert not f.exists(), f"Pre-generated destination file {d} already exists."
            
        return self
    
    @_timed("Summary")
    def summary(self) -> Self:
        """
        Print a summary of the tasks to be executed.
        """
        
        log.info("\n==================== Summary ====================")
        
        log.info("-" * 40)
        
        log.info(f"[bold blue blink]Total directories: [bold cyan blink]{len(self.pre_directories)}[/]", extra={"markup": True})
        # for item in self.pre_directories:
        #     log.info(f"{item}")
                    
        log.info("-" * 40)
        
        log.info(f"[bold blue blink]Total files to copy: [bold cyan blink]{len(self.pre_file_src)}[/]", extra={"markup": True})
        # for i in range(len(self.pre_file_src)):
        #     log.info(f"{self.pre_file_src[i]} -> {self.pre_file_dst[i]}")
        
        log.info("-" * 40)
        
        total_size = sum(f.stat().st_size for f in self.pre_file_src)
        total_size_gb = total_size / (1024 ** 3)
        log.info(f"[bold blue blink]Total file size: [bold cyan blink]{total_size_gb:.2f} GB[/]", extra={"markup": True})
        
        log.info("-" * 40)
        
        suffixes = [f.suffix.lower() for f in self.pre_file_src if f.suffix]
        top_suffixes = Counter(suffixes).most_common(10)
        max_suffix_length = max(len(suffix) for suffix, _ in top_suffixes)
        
        log.info(f"[bold blue blink]Top 10 file extensions:[/]", extra={"markup": True})
        for suffix, count in top_suffixes:
            log.info(f"[bold purple blink]{suffix:<{max_suffix_length}}[/] : {count}", extra={"markup": True})
        
        return self
    
    @_timed("Execution")
    def execute(self) -> None:
        log.info("\n==================== Execution Phase ====================")
        
        for i in track(range(len(self.pre_directories)), description="Creating directories..."):
            pre_dir = self.pre_directories[i]
            pre_dir.mkdir(parents=True, exist_ok=True)
        
        for i in track(range(len(self.pre_file_src)), description="Copying files..."):
            self._copy_file_with_metadata(self.pre_file_src[i], self.pre_file_dst[i])

    def _copy_file_with_metadata(self, src: Path, dst: Path) -> None:
        shutil.copy2(src, dst)
    

# ============================================================

# (
#     Task()
#     .add()
#     .prepare()
#     .validate()
#     .summary()
#     .execute()
# )