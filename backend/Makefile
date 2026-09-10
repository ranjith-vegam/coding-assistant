# -----------------------------
# Project metadata from pyproject.toml
# -----------------------------
VERSION := $(shell uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
PROJECT := $(shell uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['name'].lower())")

# -----------------------------
# Docker image config
# -----------------------------
REGISTRY := dev
IMAGE_NAME := $(REGISTRY)/$(PROJECT)
CONTAINER_NAME := $(PROJECT)

# -----------------------------
# Systemd service config
# -----------------------------
SERVICE_NAME := $(PROJECT)
SERVICE_FILE := deploy/systemd.service
SYSTEMD_LINK := /etc/systemd/system/$(SERVICE_NAME).service

.PHONY: dev test build build-push docker-run docker-stop docker-logs docker-shell push \
        install enable disable start stop restart \
        status logs logs-last enabled active uninstall help

# -----------------------------
# Help
# -----------------------------
help:
	@echo ""
	@echo "Dev targets:"
	@echo "  dev          - Run the backend directly with reload (uv run uvicorn --reload)"
	@echo "  test         - Run the pytest suite"
	@echo ""
	@echo "Docker targets (shared dev box; native uv run is the primary path --"
	@echo "  see systemd targets below -- since this service needs direct filesystem"
	@echo "  access to whatever workspace VS Code has open):"
	@echo "  build        - Build Docker image"
	@echo "  build-push   - Build and push Docker image"
	@echo "  docker-run   - Run Docker container"
	@echo "  docker-stop  - Stop and remove Docker container"
	@echo "  docker-logs  - Tail Docker container logs"
	@echo "  docker-shell - Shell into Docker container"
	@echo "  push         - Push Docker image"
	@echo ""
	@echo "Systemd targets (run the backend directly on this host):"
	@echo "  install      - Symlink systemd service into /etc/systemd/system"
	@echo "  enable       - Enable service on boot"
	@echo "  disable      - Disable service on boot"
	@echo "  start        - Install and start service"
	@echo "  stop         - Stop service"
	@echo "  restart      - Install and restart service"
	@echo "  status       - Show service status"
	@echo "  logs         - Tail service logs"
	@echo "  logs-last    - Show last 100 log lines"
	@echo "  enabled      - Check if service is enabled"
	@echo "  active       - Check if service is active"
	@echo "  uninstall    - Remove systemd service"
	@echo ""

# -----------------------------
# Dev targets
# -----------------------------
dev:
	uv run uvicorn coding_assistant.main:app --reload --host 127.0.0.1 --port 8765

test:
	uv run pytest -q

# -----------------------------
# Docker targets
# -----------------------------
build:
	docker build . \
		-t $(IMAGE_NAME):$(VERSION) \
		-t $(IMAGE_NAME):latest
	@echo "Built image: $(IMAGE_NAME):$(VERSION)"

build-push: build
	docker push $(IMAGE_NAME):latest
	docker push $(IMAGE_NAME):$(VERSION)

docker-run: build
	docker run -d \
		--name $(CONTAINER_NAME) \
		--network host \
		--env-file .env \
		$(IMAGE_NAME):$(VERSION)

docker-stop:
	docker stop $(CONTAINER_NAME)
	docker rm $(CONTAINER_NAME)

docker-logs:
	docker logs -f $(CONTAINER_NAME)

docker-shell:
	docker exec -it $(CONTAINER_NAME) /bin/bash

push:
	docker push $(IMAGE_NAME):$(VERSION)

# -----------------------------
# Systemd targets
# -----------------------------
install:
	@test -f $(SERVICE_FILE) || (echo "Missing service file: $(SERVICE_FILE)" && exit 1)
	sudo ln -sf $(PWD)/$(SERVICE_FILE) $(SYSTEMD_LINK)
	sudo systemctl daemon-reload
	sudo systemctl enable $(SERVICE_NAME)

enable:
	sudo systemctl enable $(SERVICE_NAME)

disable:
	sudo systemctl disable $(SERVICE_NAME)

start: install
	sudo systemctl start $(SERVICE_NAME)

stop:
	sudo systemctl stop $(SERVICE_NAME)

restart: install
	sudo systemctl restart $(SERVICE_NAME)

status:
	sudo systemctl status $(SERVICE_NAME) --no-pager

logs:
	sudo journalctl -u $(SERVICE_NAME) -f

logs-last:
	sudo journalctl -u $(SERVICE_NAME) -n 100 --no-pager

enabled:
	@systemctl is-enabled $(SERVICE_NAME)

active:
	@systemctl is-active $(SERVICE_NAME)

uninstall:
	-sudo systemctl stop $(SERVICE_NAME)
	-sudo systemctl disable $(SERVICE_NAME)
	sudo rm -f $(SYSTEMD_LINK)
	sudo systemctl daemon-reload
