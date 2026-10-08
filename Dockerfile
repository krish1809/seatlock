FROM python:3.12-slim

# No .pyc files in the bind-mounted source tree; logs are not buffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Same UID as the usual host user, so files written into the bind mount
# (e.g. by pytest) are not owned by root.
RUN useradd --uid 1000 --create-home app
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
