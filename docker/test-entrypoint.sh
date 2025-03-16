#!/usr/bin/env bash

uv sync --frozen --no-cache --no-group dev
uv run pytest
