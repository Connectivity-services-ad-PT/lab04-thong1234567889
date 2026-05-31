import os
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from http import HTTPStatus

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


SERVICE_NAME = os.getenv("SERVICE_NAME", "iot-ingestion")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.4.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")


app = FastAPI(
    title="FIT4110 Lab04 IoT Ingestion Service",
    version=SERVICE_VERSION,
)


class SensorMetric(str, Enum):
    temperature = "temperature"
    humidity = "humidity"
    motion = "motion"
    smoke = "smoke"


class SensorUnit(str, Enum):
    celsius = "celsius"
    percent = "percent"
    boolean = "boolean"
    ppm = "ppm"


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class SensorReadingCreate(BaseModel):
    device_id: str = Field(..., min_length=3)
    metric: SensorMetric
    value: float = Field(..., ge=-40, le=80)
    unit: Optional[SensorUnit] = None
    timestamp: str


class SensorReadingCreated(BaseModel):
    reading_id: str
    device_id: str
    metric: SensorMetric
    accepted: bool
    created_at: str


READINGS: List[Dict] = []


def build_problem(
    status_code: int,
    title: str,
    detail: str,
    instance: Optional[str] = None,
    problem_type: str = "about:blank",
):
    data = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }

    if instance:
        data["instance"] = instance

    return data


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        problem = build_problem(
            status_code=exc.status_code,
            title=HTTPStatus(exc.status_code).phrase,
            detail=str(exc.detail),
            instance=request.url.path,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    first_error = exc.errors()[0]

    return JSONResponse(
        status_code=422,
        content=build_problem(
            status_code=422,
            title="Validation error",
            detail=first_error["msg"],
            instance=request.url.path,
            problem_type="https://smart-campus.local/problems/validation-error",
        ),
        media_type="application/problem+json",
    )


def verify_bearer_token(
    authorization: Optional[str] = Header(default=None),
):
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=build_problem(
                status_code=401,
                title="Unauthorized",
                detail="Missing Authorization header",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )

    expected = f"Bearer {AUTH_TOKEN}"

    if authorization != expected:
        raise HTTPException(
            status_code=401,
            detail=build_problem(
                status_code=401,
                title="Unauthorized",
                detail="Invalid bearer token",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )


def next_reading_id():
    today = datetime.now().strftime("%Y%m%d")
    return f"R-{today}-{len(READINGS)+1:04d}"


def now_iso():
    # Đã sửa: Gọi trực tiếp đối tượng timezone độc lập được import ở đầu file
    return datetime.now(timezone.utc).isoformat()


@app.get("/health", response_model=HealthResponse)
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


@app.post(
    "/readings",
    response_model=SensorReadingCreated,
    status_code=201,
    dependencies=[Depends(verify_bearer_token)],
)
def create_reading(
    payload: SensorReadingCreate,
    response: Response,
):
    if (
        payload.metric == SensorMetric.temperature
        and payload.value >= 70
    ):
        response.headers["X-Warning"] = "high-temperature"

    reading_id = next_reading_id()
    created_at = now_iso()

    READINGS.append(
        {
            "reading_id": reading_id,
            "device_id": payload.device_id,
            "metric": payload.metric.value,
            "value": payload.value,
            "unit": payload.unit.value if payload.unit else None,
            "timestamp": payload.timestamp,
            "created_at": created_at,
        }
    )

    return {
        "reading_id": reading_id,
        "device_id": payload.device_id,
        "metric": payload.metric,
        "accepted": True,
        "created_at": created_at,
    }


@app.get(
    "/readings/latest",
    dependencies=[Depends(verify_bearer_token)],
)
def latest_readings(
    device_id: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
):
    data = READINGS

    if device_id:
        data = [
            x
            for x in READINGS
            if x["device_id"] == device_id
        ]

    return {"items": data[-limit:]}


@app.get(
    "/readings/{reading_id}",
    dependencies=[Depends(verify_bearer_token)],
)
def get_reading(reading_id: str):
    for item in READINGS:
        if item["reading_id"] == reading_id:
            return item

    raise HTTPException(
        status_code=404,
        detail=build_problem(
            status_code=404,
            title="Not Found",
            detail=f"Reading {reading_id} not found",
            instance=f"/readings/{reading_id}",
            problem_type="https://smart-campus.local/problems/not-found",
        ),
    )