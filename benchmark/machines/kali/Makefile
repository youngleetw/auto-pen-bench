DOCKER_COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)
ROOT_COMPOSE := ../docker-compose.yml
SERVICE := kali_master

.PHONY: build
build:
	$(DOCKER_COMPOSE) -f $(ROOT_COMPOSE) build $(SERVICE)
