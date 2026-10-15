from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def key_for(value: str) -> str:
    raw = str(value).strip().split("#", 1)[0].replace("\\", "/")
    name = raw.rsplit("/", 1)[-1]
    return Path(name).stem.lower()


def normalized(value: str) -> str:
    return os.path.normcase(
        os.path.normpath(
            os.path.expandvars(str(value).split("#", 1)[0])
        )
    )


def from_lpl(pattern: str, filters, roots, verbose=False) -> dict[str, str]:
    result = {}
    flt = [x.lower() for x in filters if x]
    roots_n = [normalized(x) for x in roots if x]

    files = glob.glob(os.path.expandvars(pattern))
    if verbose:
        print(f"[scan] pattern={pattern}")
        print(f"[scan] playlist files={len(files)}")

    item_count = 0
    core_match_count = 0
    path_match_count = 0

    for fn in files:
        p = Path(fn)
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            if verbose:
                print(f"[skip] {p}: {exc}")
            continue

        items = data.get("items", []) if isinstance(data, dict) else []
        if verbose:
            print(f"[lpl] {p.name}: {len(items)} item(s)")

        for item in items:
            if not isinstance(item, dict):
                continue

            item_count += 1
            core = (
                str(item.get("core_name", "")) + " " +
                str(item.get("core_path", ""))
            ).lower()

            path = item.get("path")
            label = str(item.get("label", "")).strip()

            core_match = (not flt) or any(x in core for x in flt)
            path_match = False

            if path and roots_n:
                try:
                    nr = normalized(path)
                    path_match = any(
                        nr == root or nr.startswith(root + os.sep)
                        for root in roots_n
                    )
                except Exception:
                    path_match = False

            if core_match:
                core_match_count += 1
            if path_match:
                path_match_count += 1

            if not core_match and not path_match:
                continue

            if path and label and label.upper() != "DETECT":
                result.setdefault(key_for(path), label)

    if verbose:
        print(f"[scan] total playlist items={item_count}")
        print(f"[scan] core-filter matches={core_match_count}")
        print(f"[scan] path-root matches={path_match_count}")
        print(f"[scan] usable labels={len(result)}")

    return result


def from_mame_xml(xml_path: Path, verbose=False) -> dict[str, str]:
    """
    Parse MAME -listxml output.

    Exclude obvious non-game entries:
      - isbios=yes
      - isdevice=yes
      - runnable=no

    Mechanical games are retained because some are still interesting to show.
    """
    result = {}
    machine_count = 0
    skipped = 0

    for event, elem in ET.iterparse(str(xml_path), events=("end",)):
        if elem.tag != "machine":
            continue

        machine_count += 1
        attrs = elem.attrib
        if (
            attrs.get("isbios") == "yes"
            or attrs.get("isdevice") == "yes"
            or attrs.get("runnable") == "no"
        ):
            skipped += 1
            elem.clear()
            continue

        name = str(attrs.get("name", "")).strip()
        desc = elem.findtext("description")
        if name and desc:
            result[key_for(name)] = desc.strip()

        elem.clear()

    if verbose:
        print(f"[xml] machines={machine_count}")
        print(f"[xml] skipped BIOS/device/non-runnable={skipped}")
        print(f"[xml] usable titles={len(result)}")

    return result


def run_mame_listxml(exe: Path, verbose=False) -> dict[str, str]:
    if not exe.exists():
        raise FileNotFoundError(f"MAME executable not found: {exe}")

    with tempfile.NamedTemporaryFile(
        prefix="retro_native_saver_mame_",
        suffix=".xml",
        delete=False,
    ) as tf:
        tmp = Path(tf.name)

    try:
        if verbose:
            print(f"[mame] {exe} -listxml")

        with tmp.open("wb") as out:
            proc = subprocess.run(
                [str(exe), "-listxml"],
                stdout=out,
                stderr=subprocess.PIPE,
            )

        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace")
            raise RuntimeError(
                f"MAME -listxml failed with exit code {proc.returncode}\n{err}"
            )

        return from_mame_xml(tmp, verbose=verbose)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--playlist", action="append", default=[])
    ap.add_argument("--core-filter", action="append", default=[])
    ap.add_argument("--rom-root", action="append", default=[])
    ap.add_argument("--mame-exe")
    ap.add_argument("--xml")
    ap.add_argument("--verbose", action="store_true")
    ns = ap.parse_args()

    titles = {}

    if ns.mame_exe:
        titles.update(
            run_mame_listxml(
                Path(os.path.expandvars(ns.mame_exe)),
                verbose=ns.verbose,
            )
        )

    if ns.xml:
        titles.update(
            from_mame_xml(
                Path(os.path.expandvars(ns.xml)),
                verbose=ns.verbose,
            )
        )

    for pattern in ns.playlist:
        found = from_lpl(
            pattern,
            ns.core_filter,
            ns.rom_root,
            verbose=ns.verbose,
        )
        for k, v in found.items():
            titles.setdefault(k, v)

    out = Path(ns.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"titles": dict(sorted(titles.items()))},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(titles)} title(s): {out}")


if __name__ == "__main__":
    main()
