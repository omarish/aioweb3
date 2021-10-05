.DEFAULT_GOAL := all
isort = isort src tests
black = black -S -l 80 --target-version py39 src tests

.PHONY: format
format:
	$(isort)
	$(black)

.PHONY: lint
lint:
	flake8 src/ tests/
	$(isort) --df
	$(black) --check

.PHONY: all
all: lint mypy

.PHONY: mypy
mypy:
	mypy src

.PHONY: clean
clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name '*.py[co]' `
	rm -f `find . -type f -name '*~' `
	rm -f `find . -type f -name '.*~' `
	rm -rf .cache
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf *.egg-info
	rm -f .coverage
	rm -f .coverage.*
	rm -rf build