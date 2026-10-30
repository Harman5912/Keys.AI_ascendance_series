"""Model registry for AI Image Studio.

The registry deliberately separates three things that are easy to confuse:

* ``capability`` — what a model can DO. ``text2img`` / ``img2img`` models
  generate pixels; ``vision`` models only *read* images and must never be
  offered as a generator. Ollama vision models (llava, qwen2.5-vl) live in
  :data:`VISION_MODELS` for exactly that reason.
* ``family`` — which ComfyUI graph can drive it (``checkpoint`` = a single
  all-in-one .safetensors loaded by CheckpointLoaderSimple).
* ``status`` — whether it can actually run on the target machine. A model is
  not "supported" just because its weights download; FLUX.2 Klein and Z-Image
  Turbo need split files, quantisation and custom nodes, so they are listed
  with the real constraints instead of a download button.

Sizes and SHA-256 values below were read from the Hugging Face repository
metadata (the LFS object id IS the file's sha256), so a downloaded checkpoint
can be verified end to end.
"""

from __future__ import annotations

# ── capability constants ───────────────────────────────────────────────────
TEXT2IMG = "text2img"
IMG2IMG = "img2img"
VISION = "vision"

# GPU this app is tuned for (RTX 3050 Laptop, 6 GB). Used for the advisory
# "fits / tight / needs offload" label; the user can still try anything.
TARGET_VRAM_GB = 6.0

_MODELS: dict[str, dict] = {
    "sd15": {
        "id": "sd15",
        "name": "Stable Diffusion 1.5",
        "short": "SD 1.5",
        "capability": "text2img",
        "capabilities": [TEXT2IMG, IMG2IMG],
        "family": "checkpoint",
        "type_label": "Checkpoint · text→image (+ img2img)",
        "description": (
            "The compatibility baseline for 6 GB laptop GPUs. Trained at "
            "512×512, needs roughly 4 GB of VRAM in fp16, and its workflow "
            "uses only ComfyUI's built-in nodes — no custom nodes required."
        ),
        "files": [
            {
                "folder": "checkpoints",
                "filename": "v1-5-pruned-emaonly.safetensors",
                "url": ("https://huggingface.co/stable-diffusion-v1-5/"
                        "stable-diffusion-v1-5/resolve/main/"
                        "v1-5-pruned-emaonly.safetensors"),
                "size_bytes": 4_265_146_304,
                "sha256": ("6ce0161689b3853acaa03779ec93eafe"
                           "75a02f4ced659bee03f50797806fa2fa"),
            },
        ],
        "vram_gb": 4.0,
        "min_vram_gb": 4.0,
        "max_edge": 768,
        "preferred_edge": 512,
        "dimension_step": 8,
        "defaults": {
            "width": 512, "height": 512, "steps": 25,
            "guidance_scale": 7.5, "sampler": "euler", "scheduler": "normal",
            "negative_prompt": ("blurry, low quality, deformed, watermark, "
                                "text, extra limbs"),
        },
        "supports_negative": True,
        "supports_img2img": True,
        "max_batch": 4,
        "custom_nodes": [],
        "license": "CreativeML OpenRAIL-M",
        "license_url": ("https://huggingface.co/stable-diffusion-v1-5/"
                        "stable-diffusion-v1-5/blob/main/LICENSE.md"),
        "license_note": (
            "Free to use, including commercially, subject to the OpenRAIL-M "
            "use restrictions (no unlawful, harmful or deceptive use). "
            "Downstream redistribution must carry the same restrictions."
        ),
        "status": "supported",
        "status_note": "Runs on 6 GB VRAM at 512×512. Start here.",
    },
    "sdxl": {
        "id": "sdxl",
        "name": "Stable Diffusion XL 1.0",
        "short": "SDXL",
        "capability": "text2img",
        "capabilities": [TEXT2IMG, IMG2IMG],
        "family": "checkpoint",
        "type_label": "Checkpoint · text→image (heavy)",
        "description": (
            "Higher quality and better prompt following, but the checkpoint "
            "alone is 6.9 GB of weights. On a 6 GB card ComfyUI has to stream "
            "weights from system RAM, so expect minutes per 1024² image and "
            "possible out-of-memory errors at full resolution. Use it at "
            "768×768 with low-VRAM mode, or skip it."
        ),
        "files": [
            {
                "folder": "checkpoints",
                "filename": "sd_xl_base_1.0.safetensors",
                "url": ("https://huggingface.co/stabilityai/"
                        "stable-diffusion-xl-base-1.0/resolve/main/"
                        "sd_xl_base_1.0.safetensors"),
                "size_bytes": 6_938_078_334,
                "sha256": ("31e35c80fc4829d14f90153f4c74cd59c90b779f"
                           "6afe05a74cd6120b893f7e5b"),
            },
        ],
        "vram_gb": 9.0,
        "min_vram_gb": 8.0,
        "max_edge": 1024,
        "preferred_edge": 1024,
        "dimension_step": 8,
        "defaults": {
            "width": 1024, "height": 1024, "steps": 25,
            "guidance_scale": 7.0, "sampler": "dpmpp_2m",
            "scheduler": "karras",
            "negative_prompt": ("blurry, low quality, deformed, watermark, "
                                "text"),
        },
        "supports_negative": True,
        "supports_img2img": True,
        "max_batch": 2,
        "custom_nodes": [],
        "license": "CreativeML OpenRAIL++-M",
        "license_url": ("https://huggingface.co/stabilityai/"
                        "stable-diffusion-xl-base-1.0/blob/main/LICENSE.md"),
        "license_note": (
            "Free for commercial use under the OpenRAIL++-M use restrictions. "
            "Redistribution must include the licence."
        ),
        "status": "warn",
        "status_note": (
            "Exceeds 6 GB VRAM — needs low-VRAM mode and is slow. Not enabled "
            "by default; no generation speed is promised before testing."
        ),
    },
    "flux2-klein-4b": {
        "id": "flux2-klein-4b",
        "name": "FLUX.2 [klein] 4B",
        "short": "FLUX.2 Klein",
        "capability": "text2img",
        "capabilities": [TEXT2IMG, IMG2IMG],
        "family": "split",
        "type_label": "Split files · text→image + editing",
        "description": (
            "Black Forest Labs' compact 2026 model with strong editing. The "
            "official fp8 build is documented at ~8.4 GB VRAM; the base "
            "variant needs around 13 GB. A GGUF quantisation can fit smaller "
            "cards, but that requires the ComfyUI-GGUF custom node and "
            "hand-picked files. Not installed or enabled here."
        ),
        "files": [],
        "vram_gb": 8.4,
        "min_vram_gb": 8.0,
        "max_edge": 1024,
        "preferred_edge": 1024,
        "dimension_step": 16,
        "defaults": {
            "width": 1024, "height": 1024, "steps": 20,
            "guidance_scale": 4.0, "sampler": "euler", "scheduler": "simple",
            "negative_prompt": "",
        },
        "supports_negative": False,
        "supports_img2img": True,
        "max_batch": 1,
        "custom_nodes": ["ComfyUI-GGUF (quantised builds only)"],
        "license": "Apache-2.0 (4B variant)",
        "license_url": "https://huggingface.co/black-forest-labs/FLUX.2-klein-4B",
        "license_note": (
            "The 4B variant is published under Apache-2.0; the 9B and dev "
            "variants are non-commercial. Verify the model card before "
            "commercial use."
        ),
        "status": "unsupported",
        "status_note": (
            "Needs ≥8 GB VRAM (fp8) or GGUF + custom nodes. Not usable on this "
            "6 GB GPU without quantisation, so no automatic download is "
            "offered."
        ),
        "docs_url": "https://docs.comfy.org/tutorials/flux/flux-2-klein",
    },
    "z-image-turbo": {
        "id": "z-image-turbo",
        "name": "Z-Image Turbo (6B)",
        "short": "Z-Image Turbo",
        "capability": "text2img",
        "capabilities": [TEXT2IMG],
        "family": "split",
        "type_label": "Split files · text→image (fast)",
        "description": (
            "Alibaba Tongyi's 6B Apache-2.0 model: about 8 steps to a 1024 px "
            "image on a modern GPU. Native ComfyUI support arrived in 2026, "
            "and the GGUF build is reported to run on 6–8 GB cards. It needs "
            "separate UNet, text-encoder and VAE files, and for 6 GB the GGUF "
            "node as well. Not installed or enabled here."
        ),
        "files": [],
        "vram_gb": 8.0,
        "min_vram_gb": 6.0,
        "max_edge": 1024,
        "preferred_edge": 1024,
        "dimension_step": 16,
        "defaults": {
            "width": 1024, "height": 1024, "steps": 8,
            "guidance_scale": 3.5, "sampler": "euler", "scheduler": "simple",
            "negative_prompt": "",
        },
        "supports_negative": False,
        "supports_img2img": False,
        "max_batch": 1,
        "custom_nodes": ["ComfyUI-GGUF (for the Q4/Q8 builds)"],
        "license": "Apache-2.0",
        "license_url": "https://huggingface.co/Tongyi-MAI/Z-Image-Turbo",
        "license_note": "Apache-2.0 — commercial use allowed.",
        "status": "requires_custom_nodes",
        "status_note": (
            "Plausible on 6 GB only with a GGUF quantisation plus the "
            "ComfyUI-GGUF node. Not verified on this machine, so no automatic "
            "download is offered."
        ),
    },
}

# Models that understand images. They are NOT image generators; showing them
# in the generator dropdown would be a lie, so they are kept in a separate
# table and only surfaced as an explanation in the diagnostics panel.
VISION_MODELS: list[dict] = [
    {
        "id": "llava",
        "name": "LLaVA (Ollama)",
        "capability": VISION,
        "type_label": "Vision-language · understands images only",
        "note": "Answers questions about an image. Cannot create one.",
    },
    {
        "id": "qwen2.5-vl",
        "name": "Qwen2.5-VL (Ollama)",
        "capability": VISION,
        "type_label": "Vision-language · understands images only",
        "note": "Image understanding / OCR. Cannot create an image.",
    },
    {
        "id": "llama3.2-vision",
        "name": "Llama 3.2 Vision (Ollama)",
        "capability": VISION,
        "type_label": "Vision-language · understands images only",
        "note": "Image understanding. Cannot create an image.",
    },
]

_STATUS_ORDER = {"supported": 0, "warn": 1, "requires_custom_nodes": 2,
                 "unsupported": 3}


def all_models() -> list[dict]:
    """Generator models only, best-fit first (supported → unsupported)."""
    return sorted(_MODELS.values(),
                  key=lambda m: (_STATUS_ORDER.get(m["status"], 9), m["name"]))


def generator_models() -> list[dict]:
    return all_models()


def vision_models() -> list[dict]:
    return [dict(m) for m in VISION_MODELS]


def get_model(model_id: str) -> dict | None:
    return _MODELS.get(str(model_id or "").strip())


def default_model_id() -> str:
    return "sd15"


def model_files(model_id: str) -> list[dict]:
    m = get_model(model_id) or {}
    return list(m.get("files") or [])


def required_folders(model_id: str) -> set[str]:
    return {f["folder"] for f in model_files(model_id) if f.get("folder")}


def fits_vram(model_id: str, vram_gb: float | None = None) -> bool:
    """Advisory check against the actual (or target) GPU memory."""
    m = get_model(model_id)
    if m is None:
        return False
    have = float(vram_gb if vram_gb is not None else TARGET_VRAM_GB)
    return have + 0.25 >= float(m.get("min_vram_gb", 99))


def vram_label(model_id: str, vram_gb: float | None = None) -> str:
    """Short human label: fits / tight / needs offload."""
    m = get_model(model_id)
    if m is None:
        return "unknown"
    need = float(m.get("min_vram_gb", 99))
    have = float(vram_gb if vram_gb is not None else TARGET_VRAM_GB)
    if have >= need + 2:
        return "fits comfortably"
    if have >= need:
        return "fits (tight)"
    return f"needs ~{need:g} GB — offload/quantisation required"


def total_download_gb(model_id: str) -> float:
    files = model_files(model_id)
    return round(sum(int(f.get("size_bytes") or 0) for f in files) / 1e9, 2)


__all__ = [
    "TEXT2IMG", "IMG2IMG", "VISION", "TARGET_VRAM_GB",
    "all_models", "generator_models", "vision_models", "get_model",
    "default_model_id", "model_files", "required_folders", "fits_vram",
    "vram_label", "total_download_gb",
]
