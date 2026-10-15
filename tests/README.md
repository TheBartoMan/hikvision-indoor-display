# Tests

Run `python3 -B -m unittest discover -s tests -v` from the repository root after
installing `requirements-test.txt` in an isolated environment.

Transport tests use real encrypted AsyncSSH exchanges over local socket pairs.
Home Assistant lifecycle tests use explicit API doubles, not a running HA instance.
All station credentials and camera data in fixtures are synthetic.

See `ACCEPTANCE.md` for live checks that unit tests do not establish.
