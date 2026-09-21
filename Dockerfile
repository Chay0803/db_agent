FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for better caching
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the project
COPY . .

# Hugging Face Spaces usually expose 7860
EXPOSE 7860

# Start the FastAPI app
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
