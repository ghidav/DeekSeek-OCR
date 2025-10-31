#
# RunPod Serverless Worker Dockerfile for DeepSeek-OCR
#
# This image packages the DeepSeek-OCR vLLM pipeline together with the
# RunPod serverless handler defined in handler.py. It follows the
# requirements outlined in https://docs.runpod.io/serverless/workers/deploy.
#

FROM vllm/vllm-openai:v0.8.5

# Switch to root to install build dependencies and Python packages.
USER root
WORKDIR /app

# Install minimal OS packages required for cloning upstream sources.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Fetch the upstream DeepSeek-OCR implementation that we patch with our customizations.
RUN git clone --depth=1 https://github.com/deepseek-ai/DeepSeek-OCR.git /tmp/deepseek-ocr \
    && mv /tmp/deepseek-ocr/DeepSeek-OCR-vllm /app/DeepSeek-OCR-vllm \
    && rm -rf /tmp/deepseek-ocr

# Copy custom overrides that adjust model configuration and pipeline behaviour.
COPY worker/overrides/custom_config.py ./DeepSeek-OCR-vllm/config.py
COPY worker/overrides/custom_image_process.py ./DeepSeek-OCR-vllm/process/image_process.py
COPY worker/overrides/custom_deepseek_ocr.py ./DeepSeek-OCR-vllm/deepseek_ocr.py

# Copy the RunPod serverless source bundle and dependency manifest.
COPY worker/ ./worker/
COPY handler.py ./handler.py
COPY requirements.txt /tmp/handler-requirements.txt

# Install Python dependencies required for the handler.
RUN pip install --no-cache-dir -r /tmp/handler-requirements.txt

# Install Python dependencies required for the OCR pipeline.
RUN pip install --no-cache-dir \
    PyMuPDF \
    img2pdf \
    einops \
    easydict \
    addict \
    Pillow \
    numpy \
    tqdm

# Additional dependencies for DeepSeek-OCR/vLLM runtime.
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    python-multipart==0.0.6

# Install flash-attn and compatible tokenizers if not already provided by the base image.
RUN pip install --no-cache-dir flash-attn==2.7.3 --no-build-isolation || echo "flash-attn already available"
RUN pip install --no-cache-dir tokenizers==0.13.3 || echo "Using pre-installed tokenizers version"

# Ensure our DeepSeek-OCR sources are discoverable.
ENV PYTHONPATH="/app/DeepSeek-OCR-vllm:${PYTHONPATH}"

# Prepare directories expected by the handler.
RUN mkdir -p /runpod/out /app/outputs
ENV RUNPOD_OUTPUT_DIR="/runpod/out"

# RunPod executes the container command directly; match documentation by running the handler in unbuffered mode.
ENTRYPOINT ["python", "-u", "/app/handler.py"]
