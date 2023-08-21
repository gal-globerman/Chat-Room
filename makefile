.ONESHELL:

dc:
	docker compose up -d
	redis-cli config set notify-keyspace-events KEA
initdb:
	aerich init-db
migrate:
	aerich migrate
	aerich upgrade
run:
	uvicorn app.main:app --reload --timeout-graceful-shutdown 1
test:
	pytest --cov=app --cov-report=html:report
