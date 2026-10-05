FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simulator.py setup_twins.py twins.json ./
USER nobody
CMD ["python", "simulator.py"]
