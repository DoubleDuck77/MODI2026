FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY contracts/ /srv/contracts/
COPY frontend/ /srv/frontend/

ENV MODI_CONTRACTS_DIR=/srv/contracts \
    MODI_FRONTEND_DIR=/srv/frontend \
    MODI_TEXTURES_DIR=/data/textures \
    MODI_COORDS_DIR=/data/coords

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
