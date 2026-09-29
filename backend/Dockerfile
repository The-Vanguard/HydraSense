# HydraSense backend (FastAPI).  Build context = repository root:  docker compose build backend
# UNTESTED: written on a machine without Docker; verify `docker compose build` before relying on it.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app

# Prebuilt wheels bundle GDAL / GEOS / PROJ (rasterio, shapely, pyproj, geopandas) -- no apt gdal needed.
COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY ml/requirements.txt /tmp/ml-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt \
    && pip install --no-cache-dir scikit-learn scipy httpx

COPY backend /app/backend
COPY ml /app/ml
# data/ is mounted at runtime (large, regenerated; see docker-compose.yml)

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
