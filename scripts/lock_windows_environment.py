"""Resolve the current project/test/build closure from installed package metadata.

This offline generator verifies one tested Windows/Python 3.11 wheel per package;
it never fetches packages or substitutes untested versions.
"""
from collections import defaultdict
from hashlib import sha256
import importlib.metadata as metadata
from pathlib import Path
import sys
import tomllib
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11):
        raise RuntimeError("This lock generator is restricted to verified Windows/Python 3.11")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pending = [Requirement(text) for text in project["project"]["dependencies"] + project["project"]["optional-dependencies"]["test"]
        + project["build-system"]["requires"] + ["pip"]]
    visited = defaultdict(set)
    versions = {}
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        wanted = {""} | set(requirement.extras)
        if wanted.issubset(visited[name]):
            continue
        distribution = metadata.distribution(requirement.name)
        if distribution.version not in requirement.specifier:
            raise RuntimeError("Installed version violates project declaration: " + name)
        versions[name] = distribution.version
        extras = wanted - visited[name]
        visited[name].update(wanted)
        for text in distribution.requires or ():
            child = Requirement(text)
            if not child.marker or any(child.marker.evaluate({"extra": extra}) for extra in extras):
                # This child has already been evaluated in the parent's extra context.
                child.marker = None
                pending.append(child)
    wheels = {}
    for path in (ROOT / ".tools/m0-wheelhouse").glob("*.whl"):
        with ZipFile(path) as archive:
            member = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
            from email.parser import BytesParser
            details = BytesParser().parsebytes(archive.read(member))
        wheels[(canonicalize_name(details["Name"]), details["Version"])] = path
    lines = ["# Verified Windows x64/Python 3.11 project, test and build dependency closure.",
             "# Generated offline from installed metadata and SHA256-checked tested wheels."]
    for name, version in sorted(versions.items()):
        path = wheels.get((name, version))
        if path is None:
            raise RuntimeError("Verified wheel missing: " + name)
        lines.append(f"{name}=={version} --hash=sha256:{sha256(path.read_bytes()).hexdigest()}")
    (ROOT / "requirements-windows-py311.lock").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Locked {len(versions)} packages from tested local wheels")


if __name__ == "__main__":
    main()
