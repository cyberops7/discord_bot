#!/usr/bin/env bash

#uv sync --frozen --no-cache --only-group test
uv run --frozen --no-default-groups --group test pytest
