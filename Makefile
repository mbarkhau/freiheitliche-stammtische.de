
.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Makefile available targets:"
	@echo "  serve     - serve the current directory on port 8085"
	@echo "  help      - display this message"


.PHONY: deps
deps:
	@echo "TODO: bun and python deps"


.PHONY: serve
serve:
	@echo "http://localhost:8085"
	@python3 -m http.server 8085 -d www
