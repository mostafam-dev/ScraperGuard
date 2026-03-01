.PHONY: test lint format typecheck docker-build docker-run

test:
	pytest --tb=short -q

lint:
	ruff check src/

format:
	ruff format src/

typecheck:
	mypy src/scraperguard/ --ignore-missing-imports

docker-build:
	docker build -t scraperguard .

docker-run:
	docker-compose up -d
