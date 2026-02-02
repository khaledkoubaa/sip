FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install pyVoIP requests gpiozero Flask

# Copy source
COPY src/ /app/src/
COPY config.ini /app/

CMD ["python", "/app/src/main.py"]