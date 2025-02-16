import os
import json
from typing import NamedTuple, Optional, List
import subprocess
import glob
import re
import urllib.parse

class TestModel(NamedTuple):
    fbx_path: str
    obj_path: Optional[str]
    mtl_path: Optional[str]
    mat_path: Optional[str]
    frame: Optional[int]

class TestCase(NamedTuple):
    root: str
    json_path: str
    title: str
    author: str
    license: str
    url: str
    extra_files: List[str]
    models: List[TestModel]

def log(message=""):
    print(message, flush=True)

def single_file(path):
    if os.path.exists(path):
        return [path]
    else:
        return []

def strip_ext(path):
    if path.endswith(".gz"):
        path = path[:-3]
    base, _ = os.path.splitext(path)
    return base

def get_fbx_files(json_path):
    base_path = strip_ext(json_path)
    yield from single_file(f"{base_path}.fbx")
    yield from single_file(f"{base_path}.ufbx.obj")
    yield from glob.glob(f"{glob.escape(base_path)}/*.fbx")

def get_obj_files(fbx_path):
    base_path = strip_ext(fbx_path)
    yield from single_file(f"{base_path}.obj.gz")
    yield from single_file(f"{base_path}.obj")
    yield from glob.glob(f"{glob.escape(base_path)}_*.obj.gz")
    yield from glob.glob(f"{glob.escape(base_path)}_*.obj")

def get_mtl_files(obj_path):
    base_path = strip_ext(obj_path)
    yield from single_file(f"{base_path}.mtl")

def get_mat_files(obj_path):
    base_path = strip_ext(obj_path)
    yield from single_file(f"{base_path}.mat")

def remove_duplicate_files(paths):
    seen = set()
    for path in paths:
        base = strip_ext(path)
        if base in seen: continue
        seen.add(base)
        yield path

def gather_case_models(json_path):
    for fbx_path in get_fbx_files(json_path):
        for obj_path in remove_duplicate_files(get_obj_files(fbx_path)):
            mtl_path = next(get_mtl_files(obj_path), None)
            mat_path = next(get_mat_files(fbx_path), None)

            fbx_base = strip_ext(fbx_path)
            obj_base = strip_ext(obj_path)

            flags = obj_base[len(fbx_base):].split("_")

            # Parse flags
            frame = None
            for flag in flags:
                m = re.match(r"frame(\d+)", flag)
                if m:
                    frame = int(m.group(1))

            yield TestModel(
                fbx_path=fbx_path,
                obj_path=obj_path,
                mtl_path=mtl_path,
                mat_path=mat_path,
                frame=frame)

        else:
            # TODO: Handle objless fbx
            pass

def gather_dataset_tasks(root_dir):
    for root, _, files in os.walk(root_dir):
        for filename in files:
            if not filename.endswith(".json"):
                continue

            path = os.path.join(root, filename)
            with open(path, "rt", encoding="utf-8") as f:
                desc = json.load(f)

            models = list(gather_case_models(path))
            if not models:
                raise RuntimeError(f"No models found for {path}")

            extra_files = [os.path.join(root, ex) for ex in desc.get("extra-files", [])]

            yield TestCase(
                root=root_dir,
                json_path=path,
                title=desc["title"],
                author=desc["author"],
                license=desc["license"],
                url=desc["url"],
                extra_files=extra_files,
                models=models,
            )

if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser("check_dataset.py --root <root>")
    parser.add_argument("--root", help="Root directory to search for .json files")
    parser.add_argument("--host-url", help="URL where the files are hosted")
    parser.add_argument("--exe", help="check_fbx.c executable")
    parser.add_argument("--verbose", action="store_true", help="Print verbose information")
    argv = parser.parse_args()

    cases = list(gather_dataset_tasks(root_dir=argv.root))

    def fmt_url(path, root=""):
        if root:
            path = os.path.relpath(path, root)
        path = path.replace("\\", "/")
        safe_path = urllib.parse.quote(path)
        return f"{argv.host_url}/{safe_path}"

    def fmt_rel(path, root=""):
        if root:
            path = os.path.relpath(path, root)
        path = path.replace("\\", "/")
        return f"{path}"

    ok_count = 0
    test_count = 0

    case_ok_count = 0

    for case in cases:

        log(f"== '{case.title}' by '{case.author}' ({case.license}) ==")
        log()

        if case.url:
            log(f"  source url: {case.url}")
        log(f"   .json url: {fmt_url(case.json_path, case.root)}")
        for extra in case.extra_files:
            log(f"   extra url: {fmt_url(extra, case.root)}")
        log()

        case_ok = True

        for model in case.models:
            test_count += 1

            args = [argv.exe]
            args.append(model.fbx_path)

            extra = []

            if model.obj_path:
                args += ["--obj", model.obj_path]

            if model.mat_path:
                args += ["--mat", model.mat_path]

            if model.frame is not None:
                extra.append(f"frame {model.frame}")
                args += ["--frame", str(model.frame)]

            name = fmt_rel(model.fbx_path, case.root)

            extra_str = ""
            if extra:
                extra_str = " [" + ", ".join(extra) + "]"

            log(f"-- {name}{extra_str} --")
            log()
            if argv.host_url:
                log(f"    .fbx url: {fmt_url(model.fbx_path, case.root)}")
                if model.obj_path:
                    log(f"    .obj url: {fmt_url(model.obj_path, case.root)}")
                if model.mtl_path:
                    log(f"    .mtl url: {fmt_url(model.mtl_path, case.root)}")
                if model.mat_path:
                    log(f"    .mat url: {fmt_url(model.mat_path, case.root)}")

            log()
            log("$ " + " ".join(args))
            log()

            try:
                subprocess.check_call(args)
                log()
                log("-- PASS --")
                ok_count += 1
            except subprocess.CalledProcessError:
                log()
                log("-- FAIL --")
                case_ok = False
            log()

        if case_ok:
            case_ok_count += 1

    log(f"{ok_count}/{test_count} files passed ({case_ok_count}/{len(cases)} test cases)")

    if ok_count < test_count:
        exit(1)
