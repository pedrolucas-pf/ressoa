FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY database.py postgres_storage.py webapp.py services.py spotify.py mail.py gunicorn.conf.py ./
COPY web ./web
RUN groupadd --gid 10001 ressoa && useradd --create-home --uid 10001 --gid 10001 ressoa
ENV RESSOA_ENV=production PORT=8000
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "webapp:create_app()"]
