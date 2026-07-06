UNAME  := $(shell uname)
VENV   := .venv
PY     := $(VENV)/bin/python
MANAGE := $(PY) backend/manage.py

.PHONY: help install install-web sync migrate backend frontend prod test example clean-example

help:
	@echo "make install       - full setup: ffmpeg + pipeline deps + .env"
	@echo "make install-web   - Python webapp deps + scaffold Next.js in webapp/ (run once)"
	@echo "make sync          - install/update pipeline Python deps via uv"
	@echo "make migrate       - run Django migrations"
	@echo "make backend       - Django only on :8000"
	@echo "make frontend      - Next.js frontend on :3000"
	@echo "make prod          - Redis + Celery + Gunicorn (production-like)"
	@echo "make test          - run the test suite"
	@echo "make example       - run the bundled example end-to-end (free, no keys needed)"
	@echo "make clean-example - remove the example's generated output"

install: ffmpeg sync env
	@echo ""
	@echo "Setup complete. Next:"
	@echo "  1. put your keys in .env (OPENAI_API_KEY, DASHSCOPE_API_KEY)"
	@echo "  2. source $(VENV)/bin/activate"
	@echo "  3. python -m pipeline.refine \"your video idea\""

sync: pyproject.toml
	uv sync --all-extras

$(VENV): pyproject.toml
	uv sync --all-extras

install-web: ffmpeg env
	uv sync --all-extras
	@if [ -d webapp ]; then \
		echo "webapp/ already exists - skipping scaffold"; \
	else \
		npx create-next-app@14 webapp --typescript --tailwind --app --no-src-dir --import-alias "@/*"; \
	fi
	@cd webapp && npm install
	@echo ""
	@echo "Web deps ready. Run: make migrate && make backend (then make frontend in another shell)"

migrate: $(VENV)
	uv sync --all-extras
	$(MANAGE) migrate

backend:
	uv sync --all-extras
	$(MANAGE) runserver 8000

frontend:
	@if [ -d webapp ]; then \
		cd webapp && npm run dev; \
	else \
		echo "No webapp/ yet - run make install-web first"; \
	fi

prod: export DJANGO_SETTINGS_MODULE = config.settings.deployment
prod:
	uv sync --all-extras
	@command -v redis-cli >/dev/null 2>&1 || (echo "ERROR: redis not found - brew install redis" && exit 1)
	@redis-cli ping >/dev/null 2>&1 || (echo "ERROR: Redis not running - brew services start redis" && exit 1)
	$(MANAGE) collectstatic --no-input
	@echo "Starting Celery workers..."
	PYTHONPATH=backend $(PY) -m celery -A config worker -l info -Q celery -n worker@%h --concurrency 4 &
	PYTHONPATH=backend $(PY) -m celery -A config worker -l info -Q images -n images@%h --concurrency 2 &
	@echo "Starting Django via gunicorn on :8000..."
	$(VENV)/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --bind [::]:8000 --worker-class gthread --workers 2 --threads 8 --timeout 120 --chdir backend

test:
	uv sync --all-extras
	$(MANAGE) test apps
	$(PY) -m pytest tests/test_pipeline_isolation.py
	$(PY) -m tests.test_expand

ffmpeg:
ifeq ($(UNAME),Darwin)
	@if ffmpeg -filters 2>/dev/null | grep -q subtitles; then \
		echo "ffmpeg with libass: OK"; \
	else \
		echo "installing ffmpeg-full (plain ffmpeg lacks libass for captions)..."; \
		brew install ffmpeg-full && brew link --overwrite ffmpeg-full; \
	fi
else
	@if command -v ffmpeg >/dev/null 2>&1; then \
		echo "ffmpeg: OK"; \
	else \
		echo "installing ffmpeg..."; \
		sudo apt-get update && sudo apt-get install -y ffmpeg; \
	fi
endif

env:
	@test -f .env || (cp .env.example .env && echo "created .env - add your keys")
	@test ! -f .env || echo ".env: OK"

# Uses the free placeholder image backend - works with no keys.
# With DASHSCOPE_API_KEY set, drop --backend placeholder for real images.
example: sync
	@test -d output/the-sharing-berry || cp -r examples/the-sharing-berry output/
	$(PY) -m pipeline.images output/the-sharing-berry --backend placeholder
	$(PY) -m pipeline.voiceover output/the-sharing-berry
	$(PY) -m pipeline.assemble output/the-sharing-berry
	@echo ""
	@echo "done - open output/the-sharing-berry/final.mp4"

clean-example:
	rm -rf output/the-sharing-berry
