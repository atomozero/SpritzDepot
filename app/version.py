"""Haiku package version comparison.

Faithful to Haiku's BPackageVersion::Compare (src/kits/package/PackageVersion.cpp)
and the version grammar documented at
https://www.haiku-os.org/docs/develop/packages/BuildingPackages.html

Structure:  major[.minor[.micro]][~preRelease]-revision

Rules, exactly as Haiku defines them (not invented here):
  1. major, minor, micro are compared in order with a *natural* compare: each is
     split into runs of digits and runs of non-digits; digit runs compare
     numerically (so 10 > 9), non-digit runs compare lexicographically, and a
     digit run outranks a non-digit run at the same position.
  2. preRelease (the '~alpha1' part): its PRESENCE makes a version OLDER. An
     empty preRelease is greater than any non-empty one, so 'R1.0' > 'R1.0~rc1'.
     When both have one, they are natural-compared.
  3. revision (the trailing '-N') is the final tiebreaker, compared numerically.

We do NOT guess when a string is unparseable: compare_versions returns None so
the caller can decline to pick a winner rather than assert a wrong order.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

_DIGITS = re.compile(r"\d+")
_SPLIT = re.compile(r"(\d+|\D+)")


class Version(NamedTuple):
    major: str
    minor: str
    micro: str
    pre_release: str          # text after '~', '' when absent
    revision: int             # trailing '-N', 0 when absent


def parse_version(s: str) -> Optional[Version]:
    """Parse 'major[.minor[.micro]][~pre]-rev' into its parts.

    Tolerant of the shapes seen in real catalogs (missing revision, extra dotted
    segments folded into micro, letters like '0.0.23b'). Returns None only when
    there is no usable version core at all."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None

    # revision: the LAST '-<digits>' group. Haiku's revision is numeric; a '-'
    # that is not followed by pure digits (e.g. 'vnc4_0.agms_1.34-1' has one at
    # the end) is still handled, since we only peel a trailing -<digits>.
    revision = 0
    m = re.search(r"-(\d+)$", s)
    if m:
        revision = int(m.group(1))
        s = s[: m.start()]

    # pre_release: everything after the first '~'
    pre_release = ""
    if "~" in s:
        s, pre_release = s.split("~", 1)

    if not s:
        return None

    # version core split on '.'; anything past micro is appended to micro so it
    # still participates in the natural compare (e.g. '0.0.86.21' -> micro '86.21').
    parts = s.split(".")
    major = parts[0] if len(parts) > 0 else "0"
    minor = parts[1] if len(parts) > 1 else ""
    micro = ".".join(parts[2:]) if len(parts) > 2 else ""
    return Version(major, minor, micro, pre_release, revision)


def _natural_compare(a: str, b: str) -> int:
    """Haiku's NaturalCompare: split each string into digit and non-digit runs,
    compare run by run. Digit runs compare numerically; a digit run is greater
    than a non-digit run at the same slot; a present run is greater than a
    missing one. Returns -1, 0, or 1."""
    if a == b:
        return 0
    ta = _SPLIT.findall(a)
    tb = _SPLIT.findall(b)
    for x, y in zip(ta, tb):
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            ix, iy = int(x), int(y)
            if ix != iy:
                return -1 if ix < iy else 1
        elif xd != yd:
            # a numeric run ranks above an alphabetic run (e.g. '1' > 'a')
            return 1 if xd else -1
        else:
            if x != y:
                return -1 if x < y else 1
    # the one with more runs left is greater ('1.2.1' > '1.2')
    if len(ta) != len(tb):
        return -1 if len(ta) < len(tb) else 1
    return 0


def compare_versions(a: str, b: str) -> Optional[int]:
    """Compare two Haiku version strings. Returns -1 (a<b), 0 (equal), 1 (a>b),
    or None if either cannot be parsed (caller should then not pick a winner)."""
    va, vb = parse_version(a), parse_version(b)
    if va is None or vb is None:
        return None

    for x, y in ((va.major, vb.major), (va.minor, vb.minor),
                 (va.micro, vb.micro)):
        d = _natural_compare(x, y)
        if d != 0:
            return d

    # pre_release: empty (a release) beats any non-empty pre_release
    if va.pre_release != vb.pre_release:
        if not va.pre_release:
            return 1
        if not vb.pre_release:
            return -1
        d = _natural_compare(va.pre_release, vb.pre_release)
        if d != 0:
            return d

    if va.revision != vb.revision:
        return -1 if va.revision < vb.revision else 1
    return 0
