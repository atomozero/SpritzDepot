"""Haiku version comparison, checked against the official spec and real data.

The spec examples come from
https://www.haiku-os.org/docs/develop/packages/BuildingPackages.html and
Haiku's BPackageVersion::Compare; the messy ones come straight from the catalog
(httrack -4 vs -5, yab 1.7.8.1 vs 1.8.2, vncserver with a non-numeric prefix).
"""
from app.version import compare_versions, parse_version, Version


def lt(a, b):
    assert compare_versions(a, b) == -1, f"expected {a} < {b}, got {compare_versions(a,b)}"
    assert compare_versions(b, a) == 1, f"expected {b} > {a}"


def eq(a, b):
    assert compare_versions(a, b) == 0, f"expected {a} == {b}, got {compare_versions(a,b)}"


# --- numeric ordering, natural (10 > 9, not lexical) ---
lt("1.9", "1.10")
lt("1.2.9", "1.2.10")
lt("2.79b-27", "2.80-1")
eq("1.0", "1.0")
print("natural numeric ordering -> ok")

# --- revision is the tiebreaker (the real httrack case) ---
lt("3.49.2-4", "3.49.2-5")
assert compare_versions("3.49.2-5", "3.49.2-4") == 1
eq("1.34-1", "1.34-1")
print("revision tiebreaker (httrack -4 < -5) -> ok")

# --- real duplicated apps: which copy is newer ---
lt("1.7.8.1-1", "1.8.2-2")          # yab: fatelk older than haikuports
lt("2.79b-27", "2.79b-28")
print("real duplicated-app versions -> ok")

# --- pre-release (~) makes a version OLDER (official spec examples) ---
lt("R1.0~alpha1", "R1.0")           # spec: R1.0~alpha1 < R1.0
lt("R1.0~beta1", "R1.0")
lt("R1.0~alpha2", "R1.0~beta1")     # spec ordering within pre-releases
lt("1.0", "1.0.1~alpha1")           # spec: 1.0 < 1.0.1~alpha1 (higher micro wins)
lt("1.0~rc1", "1.0")
print("pre-release (~) ordering per spec -> ok")

# --- letters in a segment (0.0.23b) compare naturally ---
lt("0.0.23a-1", "0.0.23b-1")
lt("0.0.23-1", "0.0.23b-1")         # bare number < number+letter at same slot
lt("0.9-1", "0.10-1")
print("alphabetic segments -> ok")

# --- parsing shape checks ---
assert parse_version("3.49.2-5") == Version("3", "49", "2", "", 5)
assert parse_version("1.0~rc1-2") == Version("1", "0", "", "rc1", 2)
assert parse_version("0.0.86.21-2") == Version("0", "0", "86.21", "", 2)
assert parse_version("7") == Version("7", "", "", "", 0)
assert parse_version("") is None
assert parse_version(None) is None
print("parsing shapes -> ok")

# --- unparseable -> None (never guess a winner) ---
assert compare_versions("", "1.0") is None
assert compare_versions("1.0", None) is None
print("unparseable declines (returns None) -> ok")

# --- the messy vncserver case must not crash; it just compares as best it can ---
r = compare_versions("vnc4_0.agms_1.34-1", "1.34-1")
assert r is not None  # both parse (non-numeric major is allowed), a total order exists
print("messy prefix compares without crashing -> ok")

print("\nPASS: Haiku version comparison")
