#!/bin/bash
git pull
docker compose down
docker compose up -d
docker compose logs -f agent