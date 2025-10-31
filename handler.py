#!/usr/bin/env python3
"""
RunPod serverless handler for the DeepSeek-OCR Docker image.

This handler downloads the requested PDF payload, executes the custom
DeepSeek-OCR PDF pipeline, and returns the generated Markdown along with
key artifacts. It is designed to be used as the `handler` entry point as
documented at https://docs.runpod.io/serverless/overview#handler-functions.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import runpod

# Resolve important paths inside the container.
ROOT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = ROOT_DIR / "custom_run_dpsk_ocr_pdf.py"

# Default output directory (overridable via job input).
DEFAULT_OUTPUT_DIR = Path(os.environ.get("RUNPOD_OUTPUT_DIR", "/tmp/runpod-output"))


class HandlerError(RuntimeError):
    """Custom exception to provide cleaner error propagation."""


def _download_to_file(url: str, suffix: str = ".pdf") -> Path:
    """Download a URL to a temporary local file."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as temp_file:
        temp_file.write(response.content)
    return Path(temp_path)


def _write_base64_file(encoded: str, suffix: str = ".pdf") -> Path:
    """Persist a base64 encoded payload to a temporary file."""
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as temp_file:
        temp_file.write(base64.b64decode(encoded))
    return Path(temp_path)


def _ensure_pdf_input(job_input: Dict[str, Any]) -> tuple[Path, list[Path]]:
    """
    Resolve the PDF input for the job and return the path plus a cleanup list.

    Expected keys in the input payload:
        - `pdf_path`: absolute path already present inside the container.
        - `pdf_url`: HTTP(S) URL to download.
        - `pdf_base64`: base64 encoded PDF bytes.
    """
    cleanup_paths: list[Path] = []

    if "pdf_path" in job_input:
        candidate = Path(job_input["pdf_path"]).expanduser()
        if not candidate.exists():
            raise HandlerError(f"Provided pdf_path does not exist: {candidate}")
        return candidate, cleanup_paths

    if "pdf_url" in job_input:
        downloaded = _download_to_file(job_input["pdf_url"])
        cleanup_paths.append(downloaded)
        return downloaded, cleanup_paths

    if "pdf_base64" in job_input:
        decoded = _write_base64_file(job_input["pdf_base64"])
        cleanup_paths.append(decoded)
        return decoded, cleanup_paths

    raise HandlerError(
        "No PDF input provided. Supply one of `pdf_path`, `pdf_url`, or `pdf_base64`."
    )


def _build_command(pdf_path: Path, output_dir: Path, prompt: Optional[str]) -> list[str]:
    """Construct the command used to execute the DeepSeek OCR pipeline."""
    command = [
        "python",
        str(SCRIPT_PATH),
        "--input",
        str(pdf_path),
        "--output",
        str(output_dir),
    ]
    if prompt:
        command.extend(["--prompt", prompt])
    return command


def _run_pipeline(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute the OCR pipeline and capture output for logging."""
    return subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        text=True,
        capture_output=True,
        check=False,
    )


def _collect_artifacts(pdf_path: Path, output_dir: Path) -> Dict[str, Any]:
    """
    Gather pipeline outputs: markdown, detection markdown, layout PDF, and images.

    Returns a dictionary containing base64-encoded assets when appropriate as well
    as absolute paths for larger artifacts so callers can fetch them via mounted
    volumes or downstream processing.
    """
    artifacts: Dict[str, Any] = {}
    pdf_name = pdf_path.name
    base_stem = pdf_name[:-4] if pdf_name.lower().endswith(".pdf") else pdf_path.stem

    markdown_path = output_dir / f"{base_stem}.mmd"
    detail_markdown_path = output_dir / f"{base_stem}_det.mmd"
    layout_pdf_path = output_dir / f"{base_stem}_layouts.pdf"
    images_dir = output_dir / "images"

    def _encode_text_file(file_path: Path) -> Optional[str]:
        if not file_path.exists():
            return None
        text_bytes = file_path.read_bytes()
        # Return plain text when reasonably sized, otherwise base64 to avoid truncation.
        if len(text_bytes) <= 500_000:
            return text_bytes.decode("utf-8")
        return base64.b64encode(text_bytes).decode("utf-8")

    markdown_content = _encode_text_file(markdown_path)
    if markdown_content is not None:
        artifacts["markdown"] = markdown_content
        artifacts["markdown_path"] = str(markdown_path)
    else:
        artifacts["markdown_missing"] = str(markdown_path)

    detection_content = _encode_text_file(detail_markdown_path)
    if detection_content is not None:
        artifacts["detection_markdown"] = detection_content
        artifacts["detection_markdown_path"] = str(detail_markdown_path)

    if layout_pdf_path.exists():
        artifacts["layout_pdf_path"] = str(layout_pdf_path)
        artifacts["layout_pdf_base64"] = base64.b64encode(
            layout_pdf_path.read_bytes()
        ).decode("utf-8")

    if images_dir.exists():
        # Create a zip archive with rendered image overlays for download.
        archive_base = output_dir / f"{base_stem}_images"
        archive_path = Path(
            shutil.make_archive(
                base_name=str(archive_base),
                format="zip",
                root_dir=str(images_dir),
            )
        )
        artifacts["images_archive_path"] = str(archive_path)

    return artifacts


def handler(event: Dict[str, Any]) -> Dict[str, Any]:
    """RunPod handler compatible with serverless execution."""
    job_input = event.get("input", {})
    prompt = job_input.get("prompt")
    output_dir = Path(job_input.get("output_dir", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path, cleanup_paths = _ensure_pdf_input(job_input)
    command = _build_command(pdf_path, output_dir, prompt)

    process = _run_pipeline(command)

    response: Dict[str, Any] = {
        "command": " ".join(command),
        "return_code": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }

    if process.returncode != 0:
        response["status"] = "failed"
    else:
        response["status"] = "succeeded"
        response.update(_collect_artifacts(pdf_path, output_dir))

    for path in cleanup_paths:
        try:
            if path.is_file():
                if path.exists():
                    path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            # If cleanup fails, continue without interrupting the response.
            pass

    return response


# Register the handler with RunPod.
runpod.serverless.start({"handler": handler})
