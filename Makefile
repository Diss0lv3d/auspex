.PHONY: check up down

check:
	./ci.sh

up:
	docker compose up -d --build

down:
	docker compose down
