# Makefile
#
# Format: use "make format". Do NOT run "black *" — the shell expands *
# to every file/dir in the repo, so black gets non-Python files and fails.
# "black ." (one path) lets black recurse and format only .py files.

.PHONY: format format-check typecheck

format:
	@echo "Running isort..."
	isort .
	@echo "Running black..."
	black .

# Check only (no write). Use in CI to fail if repo is not formatted.
format-check:
	black --check .
	isort --check-only .

# Type checking (optional). Not run by format; fix types over time then run: make typecheck
typecheck:
	mypy .
