"""Автосервис, Лаба 1: HTTP CRUD для автомобилей, данные хранятся в памяти.

Запуск:
    pip install -r requirements.txt
    uvicorn main:app --port 8000
Swagger UI: http://localhost:8000/docs
"""
import logging
import threading
import time
from typing import Annotated, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

# ---------------------------------------------------------------- логи

log = logging.getLogger("api")
log.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(_handler)
log.propagate = False

# ---------------------------------------------------------------- модели

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Plate = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20),
]
Year = Annotated[int, Field(strict=True, ge=1900, le=2100)]


class CarIn(BaseModel):
    """Тело для POST и PUT: все поля обязательны."""
    brand: Text
    plate: Plate
    owner: Text
    year: Year


class CarPatch(BaseModel):
    """Тело для PATCH: любые поля, но если поле передано, оно не может быть null."""
    brand: Optional[Text] = None
    plate: Optional[Plate] = None
    owner: Optional[Text] = None
    year: Optional[Year] = None

    @field_validator("*", mode="before")
    @classmethod
    def not_null(cls, v):
        if v is None:
            raise ValueError("значение не может быть null")
        return v


class Car(CarIn):
    id: int


# ---------------------------------------------------------------- хранилище в памяти

cars: dict[int, dict] = {}
_lock = threading.Lock()
_next_id = 1


def find_car(car_id: str) -> dict:
    if not car_id.isdigit() or int(car_id) not in cars:
        raise HTTPException(404, "Автомобиль не найден")
    return cars[int(car_id)]


# ---------------------------------------------------------------- приложение

app = FastAPI(title="Автосервис: автомобили (Лаба 1)")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    log.info("%s %s %d %.1fms", request.method, request.url.path, response.status_code, ms)
    return response


# --- единый формат ошибок

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    err = exc.errors()[0]
    # имя поля: первый строковый элемент пути, кроме body/query/path
    field = next(
        (p for p in err["loc"] if isinstance(p, str) and p not in ("body", "query", "path")),
        "body",
    )
    kind = err["type"]
    if kind == "json_invalid":
        text = "Некорректный JSON"
    elif kind == "missing":
        text = f"Поле {field} обязательно"
    else:
        text = f"Поле {field}: {err['msg']}"
    return JSONResponse({"error": text, "field": field}, status_code=400)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


# --- эндпоинты

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/cars", response_model=Car, status_code=201)
def create_car(data: CarIn, response: Response):
    global _next_id
    with _lock:
        car = {"id": _next_id, **data.model_dump()}
        cars[_next_id] = car
        _next_id += 1
    response.headers["Location"] = f"/api/cars/{car['id']}"
    return car


@app.get("/api/cars", response_model=list[Car])
def list_cars(
    response: Response,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    brand: Optional[str] = None,
    plate: Optional[str] = None,
    owner: Optional[str] = None,
    year: Optional[int] = None,
):
    items = list(cars.values())
    for name, value in (("brand", brand), ("plate", plate), ("owner", owner)):
        if value is not None:
            items = [c for c in items if c[name].casefold() == value.strip().casefold()]
    if year is not None:
        items = [c for c in items if c["year"] == year]

    response.headers["X-Total-Count"] = str(len(items))
    return items[offset : offset + limit]


@app.get("/api/cars/{car_id}", response_model=Car)
def get_car(car_id: str):
    return find_car(car_id)


@app.put("/api/cars/{car_id}", response_model=Car)
def replace_car(car_id: str, data: CarIn):
    car = find_car(car_id)
    car.update(data.model_dump())
    return car


@app.patch("/api/cars/{car_id}", response_model=Car)
def patch_car(car_id: str, data: CarPatch):
    car = find_car(car_id)
    car.update(data.model_dump(exclude_unset=True))
    return car


@app.delete("/api/cars/{car_id}", status_code=204)
def delete_car(car_id: str):
    car = find_car(car_id)
    del cars[car["id"]]
    return Response(status_code=204)
