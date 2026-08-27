.PHONY: check test package

check:
	python3 scripts/check_repo.py
	python3 -m unittest discover -s tests -v

test: check

package: check
	python3 scripts/package_plugin.py
