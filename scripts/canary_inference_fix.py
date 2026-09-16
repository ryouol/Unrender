"""Bounded cold/warm check of the production provider; invokes paid L4 inference."""

import json
from pathlib import Path

import modal

import modal_train as provider

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("unrender-provider-fix-canary")
image = provider.infer_image.add_local_file(ROOT / "modal_train.py", "/root/modal_train.py")


@app.function(
    image=image,
    volumes={provider.INFER_V: provider.INFER_VOL},
    gpu=provider.GPU,
    cpu=4,
    memory=32768,
    timeout=300,
    retries=0,
    max_containers=1,
    scaledown_window=2,
)
def check(
    image_bytes: bytes,
    revision: str,
    cpu_threads: int = 0,
    max_tokens: int = 0,
    profile: bool = False,
    max_pixels: int = 0,
    flash_sdp: bool = False,
):
    import time
    from contextlib import nullcontext

    import torch
    from transformers import AutoProcessor

    from modal_train import infer_one
    from unrender.eval import providers

    original_threads = torch.get_num_threads()
    if cpu_threads:
        torch.set_num_threads(cpu_threads)
    print({"original_cpu_threads": original_threads, "cpu_threads": torch.get_num_threads()})
    observed = {}
    original_load = AutoProcessor.from_pretrained

    def load(*args, **kwargs):
        if max_pixels:
            kwargs["max_pixels"] = max_pixels
        proc = original_load(*args, **kwargs)
        if max_pixels:
            proc.image_processor.size = {**proc.image_processor.size, "longest_edge": max_pixels}
            if hasattr(proc.image_processor, "max_pixels"):
                proc.image_processor.max_pixels = max_pixels
        original_decode = proc.decode

        def decode(tokens, **decode_kwargs):
            observed["generated_tokens"] = len(tokens)
            observed["tail_tokens"] = proc.tokenizer.convert_ids_to_tokens(tokens[-16:].tolist())
            return original_decode(tokens, **decode_kwargs)

        proc.decode = decode
        return proc

    AutoProcessor.from_pretrained = load
    original_provider = providers.hf_vlm_provider
    profile_next = False

    def measured(*args, **kwargs):
        if max_tokens:
            providers.HF_GEN_CONFIG["max_new_tokens"] = max_tokens
        if profile_next:
            with torch.profiler.profile(
                activities=[
                    torch.profiler.ProfilerActivity.CPU,
                    torch.profiler.ProfilerActivity.CUDA,
                ]
            ) as trace:
                result = original_provider(*args, **kwargs)
            trace_path = Path(provider.INFER_V) / "diagnostics/provider-image-fix-trace.json"
            trace_path.parent.mkdir(exist_ok=True)
            trace.export_chrome_trace(str(trace_path))
            provider.INFER_VOL.commit()
            observed["profile_cpu"] = trace.key_averages().table(
                sort_by="self_cpu_time_total", row_limit=15
            )
            observed["profile_cuda"] = trace.key_averages().table(
                sort_by="self_cuda_time_total", row_limit=15
            )
        else:
            from torch.nn.attention import SDPBackend, sdpa_kernel

            with sdpa_kernel(SDPBackend.FLASH_ATTENTION) if flash_sdp else nullcontext():
                result = original_provider(*args, **kwargs)
        observed["stages"] = dict(kwargs.get("timings", {}))
        return result

    providers.hf_vlm_provider = measured

    results = []
    for phase in ("cold", "warm"):
        profile_next = profile and phase == "warm"
        started = time.perf_counter()
        result = infer_one.local(
            image_bytes, "modal-volume/unrender-inference-cache", revision, revision
        )
        elapsed = time.perf_counter() - started
        proc, model = next(iter(providers._HF_CACHE.values()))
        diagnostics = {
            **observed,
            "original_cpu_threads": original_threads,
            "cpu_threads": torch.get_num_threads(),
            "device_map": {k: str(v) for k, v in model.hf_device_map.items()},
            "dtype": str(model.dtype),
            "flash_sdp": flash_sdp,
            "image_size": proc.image_processor.size,
            "attention": model.config._attn_implementation,
            "use_cache": model.generation_config.use_cache,
            "output_tokens": len(proc.tokenizer.encode(result["raw"])),
        }
        print(diagnostics)
        results.append(
            {"phase": phase, "elapsed_seconds": elapsed, "diagnostics": diagnostics, **result}
        )
    return results


@app.local_entrypoint()
def main(
    image_path: str,
    output: str,
    revision: str,
    cpu_threads: int = 0,
    max_tokens: int = 0,
    profile: bool = False,
    max_pixels: int = 0,
    flash_sdp: bool = False,
):
    results = check.remote(
        Path(image_path).read_bytes(),
        revision,
        cpu_threads,
        max_tokens,
        profile,
        max_pixels,
        flash_sdp,
    )
    Path(output).write_text(json.dumps(results, indent=2))
    print(
        json.dumps(
            [
                {
                    "phase": r["phase"],
                    "seconds": r["elapsed_seconds"],
                    "valid": r["json"] is not None,
                    "release": r["provider_release"],
                }
                for r in results
            ],
            indent=2,
        )
    )
