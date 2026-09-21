"""Executable form of the privacy rule.

docs/privacy.md says Hall Check stores counts and never frames. A policy that
lives only in a markdown file survives exactly until the first person who has
not read it needs a debug image. This module reads the worker's source and
fails the build if a way to persist pixels appears in it.

The check is deliberately blunt. If a legitimate change trips it, the right
response is to look hard at whether the change really needs to write image
data, and if it genuinely does, to make that case explicitly here rather than
routing around the test.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import hallcheck
from hallcheck.detect import YoloPersonDetector

PACKAGE_ROOT = Path(hallcheck.__file__).parent
SOURCE_FILES = sorted(PACKAGE_ROOT.rglob("*.py"))

#: Attribute names that write pixels or arrays to durable storage.
BANNED_CALLS = frozenset(
    {
        "imwrite",  # cv2
        "imsave",  # matplotlib, skimage
        "savefig",  # matplotlib
        "save",  # PIL.Image.save, numpy.save, torch.save
        "savez",
        "savez_compressed",
        "tofile",  # numpy
        "write_bytes",  # pathlib
        "put_object",  # boto3 / S3-alikes
        "upload_file",
        "upload_fileobj",
    }
)

#: Ultralytics keyword arguments that make the library write to disk by itself.
BANNED_KEYWORDS = frozenset({"save", "save_txt", "save_crop", "save_conf", "save_frames"})


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_truthy(node: ast.expr) -> bool:
    """Whether a keyword argument is anything other than a literal False/None."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    # A non-literal (a variable, a call) could be anything, so treat it as a
    # risk rather than assuming it is off.
    return True


def test_source_files_were_discovered():
    # Guards against the scan silently passing because it found nothing.
    assert len(SOURCE_FILES) >= 8, f"only found {len(SOURCE_FILES)} modules to scan"


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: p.name)
def test_no_module_persists_image_data(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    offences: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name = _called_name(node)
        if name in BANNED_CALLS:
            offences.append(f"line {node.lineno}: calls {name}(), which writes to storage")

        for keyword in node.keywords:
            if keyword.arg in BANNED_KEYWORDS and _is_truthy(keyword.value):
                offences.append(
                    f"line {node.lineno}: passes {keyword.arg}= enabled, "
                    "which makes the library write frames to disk"
                )

        # open(path, "wb") and friends.
        if name == "open":
            mode_args = list(node.args[1:2])
            mode_args += [kw.value for kw in node.keywords if kw.arg == "mode"]
            for argument in mode_args:
                if not (isinstance(argument, ast.Constant) and isinstance(argument.value, str)):
                    continue
                mode = argument.value
                if "b" in mode and any(flag in mode for flag in ("w", "a", "x", "+")):
                    offences.append(f"line {node.lineno}: opens a binary file for writing")

    if offences:
        listed = "\n".join(f"  - {offence}" for offence in offences)
        relative = path.relative_to(PACKAGE_ROOT.parent)
        raise AssertionError(f"{relative} violates the privacy rule:\n{listed}")


def test_detector_pins_every_save_flag_off():
    """The detector must not rely on Ultralytics' defaults.

    Ultralytics reads some of these from a settings file in the user's home
    directory. Depending on its default means depending on a file this
    repository does not control staying the way we found it.
    """
    source = inspect.getsource(YoloPersonDetector._detect_boxes)
    for flag in ("save=False", "save_txt=False", "save_conf=False", "save_crop=False"):
        assert flag in source, f"detector does not explicitly set {flag}"


def test_the_only_public_detection_result_is_an_integer():
    signature = inspect.signature(YoloPersonDetector.count_in_roi)
    assert signature.return_annotation in (int, "int"), (
        "count_in_roi must return an int; returning boxes or a frame would put "
        "per-person position data on a path where it can be stored"
    )
