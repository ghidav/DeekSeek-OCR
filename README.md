# RunPod DeepSeek-OCR Worker

Serverless PDF-to-Markdown worker for [RunPod](https://www.runpod.io/) built on top of DeepSeek-OCR (via vLLM). The container mirrors the official RunPod layout—`Dockerfile`, `handler.py`, `requirements.txt`, and a `worker/` directory with DeepSeek overrides.

## Input Schema

Send jobs to the handler with an `input` payload containing:

- `pdf_url` *(string)* – HTTPS URL to download.
- `pdf_path` *(string)* – Absolute path to a PDF already present in the container.
- `pdf_base64` *(string)* – Base64 encoded PDF bytes.
- `prompt` *(string, optional)* – Custom DeepSeek prompt (defaults to the value in `worker/overrides/custom_config.py`).
- `output_dir` *(string, optional)* – Directory for artifacts (defaults to `/tmp/runpod-output` or the value of `RUNPOD_OUTPUT_DIR`).

Exactly one of `pdf_url`, `pdf_path`, or `pdf_base64` must be supplied.

## Example Request

```json
{
  "input": {
    "pdf_url": "https://arxiv.org/pdf/2109.00256.pdf",
    "prompt": "<image>\\n<|grounding|>Convert this document to Markdown.",
    "output_dir": "/runpod/out"
  }
}
```

## Output Shape

The handler returns:

- `status`: `"succeeded"` or `"failed"`.
- `command`: Exact CLI used to invoke the DeepSeek pipeline.
- `return_code`: Exit code from the subprocess.
- `stdout`, `stderr`: Captured text output.
- `markdown`, `detection_markdown`, `layout_pdf_base64`: Optional base64-encoded artifacts when files exist and are reasonably sized.
- `markdown_path`, `detection_markdown_path`, `layout_pdf_path`, `images_archive_path`: Absolute paths to on-disk artifacts for large results.

Artifacts are written under `output_dir` so they can be streamed back to RunPod volumes.

## Model & Runtime Notes

- The image expects DeepSeek-OCR weights at `/app/models/deepseek-ai/DeepSeek-OCR` (override with `MODEL_PATH` env).
- GPU with CUDA 11.8+ is required; the Dockerfile is based on `vllm/vllm-openai:v0.8.5`.
- Key runtime knobs (e.g., `MAX_CONCURRENCY`, `GPU_MEMORY_UTILIZATION`) are still read from the original DeepSeek config after our overrides are copied in.

## Building & Deploying

```bash
# Build locally
docker build -t ghcr.io/<your-org>/runpod-deepseek-ocr .

# Push to your registry
docker push ghcr.io/<your-org>/runpod-deepseek-ocr
```

Attach the image to a RunPod Serverless Worker or Hub repo following the [RunPod deployment docs](https://docs.runpod.io/serverless/workers/deploy).

## Project Structure

```
.
├── Dockerfile            # Builds the worker image
├── handler.py            # RunPod handler entry point
├── requirements.txt      # Minimal handler dependencies
└── worker/
    ├── overrides/        # Replacements for DeepSeek-OCR modules
    │   ├── custom_config.py
    │   ├── custom_deepseek_ocr.py
    │   └── custom_image_process.py
    └── pipelines/        # CLI entry points invoked by the handler
        ├── custom_run_dpsk_ocr_pdf.py
        ├── custom_run_dpsk_ocr_image.py
        └── custom_run_dpsk_ocr_eval_batch.py
```

All DeepSeek patches stay under `worker/`, keeping the root clean and aligned with the reference RunPod worker template.
