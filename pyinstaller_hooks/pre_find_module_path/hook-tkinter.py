from pathlib import Path
import sys


def pre_find_module_path(hook_api):
    stdlib_dir = Path(sys.base_prefix) / "Lib"
    hook_api.search_dirs = [str(stdlib_dir)]
