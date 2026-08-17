FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Docling pulls in torch transitively, and pip's default Linux wheel is the CUDA
# build: ~2.7 GB of nvidia/* libraries that can never fire here (no GPU on this
# host — layout models run in the on-demand docling container). Install the CPU
# wheels from PyTorch's CPU index first, so the requirements install below finds
# torch/torchvision already satisfied and never reaches for the CUDA build.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.12.1 torchvision==0.27.1

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
