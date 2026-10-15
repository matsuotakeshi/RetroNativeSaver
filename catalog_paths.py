"""Short-lived directory metadata, never a persistent ROM eligibility cache.

Windows scandir carries file attributes in the enumeration result. For an
ordinary file, resolving its parent once is equivalent to resolving that file.
Reparse points, unusual spellings, missing entries and unreadable directories
use Path's original operations. No cache survives a scan or favorite refresh.
"""
import os
from pathlib import Path
import stat


class CatalogPaths:
    def __init__(self):
        self.directories = {}
        self.parents = {}

    def ordinary_entry(self, path):
        if os.name != 'nt':
            return None
        parent = path.parent
        if parent not in self.directories:
            try:
                with os.scandir(parent) as entries:
                    self.directories[parent] = {e.name: e for e in entries}
            except OSError:
                self.directories[parent] = {}
        entry = self.directories[parent].get(path.name)
        if entry is not None:
            try:
                info = entry.stat(follow_symlinks=False)
                attributes = getattr(info, 'st_file_attributes', None)
                if attributes is not None and not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    return entry
            except OSError:
                pass
        return None

    def is_file(self, path):
        entry = self.ordinary_entry(path)
        return entry.is_file() if entry is not None else path.is_file()

    def canonical(self, path):
        path = Path(path)
        try:
            entry = self.ordinary_entry(path)
            if entry is not None and entry.is_file():
                parent = path.parent
                if parent not in self.parents:
                    # strict ensures that a failed parent lookup does not turn
                    # a partial lexical resolution into a false favorite match.
                    self.parents[parent] = None
                    self.parents[parent] = parent.resolve(strict=True)
                resolved = (self.parents[parent] / entry.name
                            if self.parents[parent] is not None else path.resolve())
            else:
                resolved = path.resolve()
            return str(resolved).replace('\\', '/').casefold()
        except (OSError, RuntimeError):
            # Preserve the original full-path fallback (including non-strict
            # resolution when only the parent optimization failed).
            try:
                return str(path.resolve()).replace('\\', '/').casefold()
            except (OSError, RuntimeError):
                return str(path).replace('\\', '/').casefold()
