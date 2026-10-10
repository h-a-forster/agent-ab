# pkgres

Semantic versions, npm-style version ranges and a small backtracking dependency resolver.

```python
from pkgres import PackageIndex, resolve, install_order, dump

index = PackageIndex.from_dict({
    "app":  {"1.0.0": {"left": "^1.2.0", "right": "~2.0"}},
    "left": {"1.2.0": {}, "1.3.1": {}, "2.0.0": {}},
    "right": {"2.0.4": {}},
})
res = resolve(index, {"app": "*"})     # app 1.0.0, left 1.3.1, right 2.0.4
install_order(res, index)              # ['left', 'right', 'app']
print(dump(res))
```

Documented behaviour:

* Version precedence follows semver 2.0: build metadata is ignored; a prerelease sorts before
  its release; prerelease identifiers are compared one by one, numeric identifiers as numbers
  (`alpha.2 < alpha.10`) and numeric ones before alphanumeric ones.
* Ranges: `^` allows changes that do not modify the left-most non-zero number
  (`^1.2.3` = `>=1.2.3 <2.0.0`, `^0.2.3` = `>=0.2.3 <0.3.0`, `^0.0.3` = `>=0.0.3 <0.0.4`,
  `^0.2` = `>=0.2.0 <0.3.0`, `^0` = `>=0.0.0 <1.0.0`); `~1.2.3` and `~1.2` stay within the minor
  (`<1.3.0`), `~1` stays within the major (`<2.0.0`); partial versions are ranges (`1` and `1.x`
  = `>=1.0.0 <2.0.0`, `1.2` = `>=1.2.0 <1.3.0`); `<=1` means `<2.0.0` and `>1` means `>=2.0.0`;
  `A - B` is inclusive, and a partial upper bound includes everything with that prefix
  (`1.2.3 - 2` = `>=1.2.3 <3.0.0`); `||` joins alternatives.
* A prerelease version only matches a comparator set that itself mentions a prerelease of the
  same `major.minor.patch` (so `>=1.0.0` never selects `2.0.0-beta.1`). This applies to
  `Range.matches`, `Range.filter`, `max_satisfying`, `min_satisfying` and to the resolver.
* The resolver decides packages in alphabetical order, tries the highest version first and
  must backtrack cleanly: constraints added by an abandoned choice are forgotten.
* `install_order` lists dependencies first; among packages that are ready at the same
  moment the alphabetically smallest comes first.
* Package names may be scoped (`@org/lib`); lockfile lines and `name@range` requirements split
  at the *last* `@` (a leading `@` belongs to the name).

Run the tests with `python -m unittest discover -s tests -t .`.
