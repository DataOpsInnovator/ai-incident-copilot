# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""FastAPI surface for the Incident Copilot."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from copilot.agent.copilot import diagnose as run_agent

app = FastAPI(title="AI Incident Copilot", version="0.1.0")


class DiagnoseRequest(BaseModel):
    query: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/diagnose")
def diagnose(req: DiagnoseRequest) -> dict:
    return run_agent(req.query)
