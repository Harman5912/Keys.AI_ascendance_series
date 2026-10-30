"""ComfyUI workflows built from built-in nodes only.

The graph is the API format ComfyUI's ``POST /prompt`` expects (node id →
{class_type, inputs}), not the UI JSON. Only core nodes are used —
CheckpointLoaderSimple, CLIPTextEncode, EmptyLatentImage / LoadImage,
VAEEncode, KSampler, VAEDecode, SaveImage — so a fresh ComfyUI install can run
these without any custom node pack.

Only settings the selected workflow actually supports are emitted; a request
field is never forwarded blindly to the backend.
"""

from __future__ import annotations

from core.image_studio import registry


class WorkflowError(ValueError):
    """The model cannot produce a workflow for this request."""


def _checkpoint_filename(model: dict, installed: list[str] | None) -> str:
    files = model.get("files") or []
    if not files:
        raise WorkflowError(
            f"{model['name']} has no built-in workflow: its weights are split "
            "across several files and need model-specific loader nodes.")
    wanted = files[0]["filename"]
    if installed:
        if wanted in installed:
            return wanted
        # Same checkpoint under a sub-folder (e.g. "sd15/v1-5....safetensors").
        for name in installed:
            if name.split("/")[-1] == wanted.split("/")[-1]:
                return name
    return wanted


def sample_settings(model: dict, request: dict) -> dict:
    """Effective sampler settings — request values win, model defaults fill in."""
    defaults = model.get("defaults") or {}
    steps = request.get("steps")
    cfg = request.get("guidance_scale")
    return {
        "steps": int(steps if steps is not None else defaults.get("steps", 25)),
        "cfg": float(cfg if cfg is not None
                     else defaults.get("guidance_scale", 7.5)),
        "sampler": str(request.get("sampler")
                       or defaults.get("sampler") or "euler"),
        "scheduler": str(request.get("scheduler")
                         or defaults.get("scheduler") or "normal"),
    }


def build_graph(model: dict, request: dict, *, job_id: str,
                uploaded_image: str | None = None,
                checkpoint: str | None = None) -> dict:
    """The ComfyUI API graph for this request.

    ``uploaded_image`` is the name ComfyUI returned from /upload/image; when it
    is set the graph switches from text2img to img2img.
    """
    if model.get("family") != "checkpoint":
        raise WorkflowError(
            f"{model['name']} needs a model-specific workflow (split UNet / "
            "text encoder / VAE) which this build does not provide.")

    ckpt = checkpoint or _checkpoint_filename(model, None)
    s = sample_settings(model, request)
    width = int(request.get("width") or 512)
    height = int(request.get("height") or 512)
    batch = int(request.get("batch_size") or 1)
    seed = int(request.get("seed") or 0)
    prompt = str(request.get("prompt") or "")
    negative = str(request.get("negative_prompt") or "")

    graph: dict = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["1", 1]}},
    }

    if uploaded_image:
        denoise = float(request.get("denoise_strength") or 0.65)
        denoise = max(0.05, min(1.0, denoise))
        graph["4"] = {"class_type": "LoadImage",
                      "inputs": {"image": uploaded_image}}
        graph["5"] = {"class_type": "VAEEncode",
                      "inputs": {"pixels": ["4", 0], "vae": ["1", 2]}}
        latent = ["5", 0]
    else:
        graph["4"] = {"class_type": "EmptyLatentImage",
                      "inputs": {"width": width, "height": height,
                                 "batch_size": batch}}
        denoise = 1.0
        latent = ["4", 0]

    graph["6"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": s["steps"],
            "cfg": s["cfg"],
            "sampler_name": s["sampler"],
            "scheduler": s["scheduler"],
            "denoise": denoise,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": latent,
        },
    }
    graph["7"] = {"class_type": "VAEDecode",
                  "inputs": {"samples": ["6", 0], "vae": ["1", 2]}}
    graph["8"] = {"class_type": "SaveImage",
                  "inputs": {"images": ["7", 0],
                             "filename_prefix": f"KeysAI/keysai_{job_id}"}}
    return graph


def workflow_summary(model: dict, request: dict) -> dict:
    """The generation settings actually used — stored with the image."""
    s = sample_settings(model, request)
    out = {
        "model": model.get("name", ""),
        "model_id": model.get("id", ""),
        "width": int(request.get("width") or 512),
        "height": int(request.get("height") or 512),
        "steps": s["steps"],
        "guidance_scale": s["cfg"],
        "sampler": s["sampler"],
        "scheduler": s["scheduler"],
        "seed": int(request.get("seed") or 0),
        "batch_size": int(request.get("batch_size") or 1),
        "output_format": str(request.get("output_format") or "png"),
    }
    if request.get("input_image"):
        out["input_image"] = str(request.get("input_image"))
        out["denoise_strength"] = float(request.get("denoise_strength") or 0.65)
    return out


def capability_note(model: dict) -> str:
    caps = model.get("capabilities") or [registry.TEXT2IMG]
    labels = []
    if registry.TEXT2IMG in caps:
        labels.append("text→image")
    if registry.IMG2IMG in caps:
        labels.append("image→image")
    return " · ".join(labels)


__all__ = ["WorkflowError", "build_graph", "sample_settings",
           "workflow_summary", "capability_note"]
