FROM postgres:16-alpine

# SQL files in this folder are executed automatically at first container startup.
COPY docker/db/init/ /docker-entrypoint-initdb.d/
