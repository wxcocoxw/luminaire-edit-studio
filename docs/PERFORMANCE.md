# Performance and compatibility

The v1.3.2 runtime was checked locally with ComfyUI 0.42.0, frontend 1.57.1,
Python 3.13.11, Torch 2.10.0+cu130, comfy-kitchen 0.2.39, RTX 4090 24 GB and
64 GB system RAM. These are tested versions, not a claim of compatibility with
every older or newer installation.

## Attention comparison

A local 2026-10-29 comparison used one product image and prompt, 2 MP, the base
INT8 transformer, W4A8 text encoder, texture-fix VAE, 40 steps, CFG 1 and
Euler/simple. Three seeds were paired between backends, with separate warm-ups.
Both `--disable-dynamic-vram` and `--disable-async-offload` were enabled.

| Backend | Median sampler time | Median complete warm job |
| --- | ---: | ---: |
| Comfy Kitchen INT8 | 55.66 s | 57.43 s |
| SageAttention 2.2 | 54.20 s | 56.16 s |

Sage reduced sampler time about 2.6% in this comparison. One seed favored Kitchen;
VRAM was effectively unchanged. This small difference does not establish a general
speed winner. The inspected first output pair looked similar; pixel differences
across the three seeds were nonzero. Other inputs, GPUs, clocks, software and
launch profiles can give different results.

Counters recorded 1,312 Sage CUDA calls and 64 expected PyTorch mask fallbacks per
40-step job, with no Sage CUDA exceptions. Kitchen recorded 1,376 native quantized
attention calls. Counts are not percentages of GPU time or a GPU-profiler trace.
Qwen's masked block-causal prefix preparation accounts for the native Sage fallback.

## Attention options

Auto retains the host/model's existing attention selection. Explicit PyTorch and
Comfy Kitchen use native per-model overrides. Explicit Sage requires compatible
Sage/Triton packages and a backend restart. On the tested Windows installation,
Sage 2.2.0 post6 and triton-windows 3.6.0.post26 were used; this does not prescribe
those wheels for another Python/Torch/CUDA combination.

Follow the [Sage Windows maintainer](https://github.com/woct0rdho/SageAttention)
and [Triton Windows installation guidance](https://github.com/triton-lang/triton-windows)
for matching binaries and portable Python headers. Comfy Kitchen's kernels are
maintained [upstream](https://github.com/Comfy-Org/comfy-kitchen). Installing the
Studio workflow does not install or globally enable these optional backends.

## Memory and stalls

An overlapping Quality/Draft transformer load stalled during local validation.
The v1.3.2 sampler now unloads only the preceding transformer family in both
switch directions. A 2 MP Quality -> .5 MP six-step Draft -> 2 MP Quality cycle
completed after that fix. Other model caches remain under native management.

The two conservative launch flags above were used for the full attention and
transition comparisons. Separate smaller cold trials completed with each flag
combination, including defaults. Cold initialization differed; those trials do
not establish warm throughput or a universal hang fix. The installer never changes
launch flags automatically. Test one change at a time using fixed inputs/settings.

Reduce working/reference area when memory is tight. AI upscaling's full native
intermediate can be large. Neither the cache nor an attention backend removes the
base model's memory requirements.
