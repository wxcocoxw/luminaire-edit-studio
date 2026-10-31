# Workflow usage

## Shared controls and task selection

Select one of the eight task modes. The Studio Bus uses KJNodes Set/Get nodes to
share model, seed, working-area, reference and delivery settings across native
subgraphs. Task switching preserves separate optional-feature states. Leave
unneeded prompt enhancement, guidance and alignment branches disabled.

The source image is separate from the additional-reference bank. Preserve its
ordering; image slots affect conditioning. Quality retains up to eight additional
references. Draft permits at most three total images, including source and any
full-source context inserted by a task. T2I keeps explicit output dimensions.

## Protected editing

In Edit, paint white over regions to preserve in the source loader's mask editor,
then enable protection. Growth expands the protected core. Feathering blends
outward without weakening the fully protected core. Use the overlay preview.
Masks must match source dimensions.

In Masked Edit, choose **White edits** or **White protects**. The contextual crop
receives the edit mask, and restoration receives its protected complement. Inspect
the context crop before rendering.

Restoration aligns the result to the original source canvas and restores protected
source pixels exactly at that stage. A later resize, flatten or grain operation
can change them. Keep input size, preserve alpha and zero grain when exact delivery
of the protected core is required. Other tasks retain their own compositing and
alpha behavior.

## Delivery

Presets include Keep input size, Scale input, Custom, HD/UHD landscape, square
1080, portrait 4:5 and vertical 9:16. Choose centered Crop, Pad or Stretch.
Transparent padding requires preserved alpha. Background can be black, white or
transparent where supported.

Lanczos/Bicubic resizing needs no upscale weights. AI requires an installed model
selected in the delivery settings. AI's native-scale inference is followed by the
exact requested output dimensions: a 4x model with a 2x delivery request finishes
at 2x of the input to finishing. The larger intermediate still consumes memory.

RGB grain is deterministic for a fixed seed and output shape, runs after final
sizing, and preserves alpha. Same-size folder items with a fixed displayed seed
share the grain pattern. Tensor batches receive distinct deterministic patterns.
The CLI can derive recorded per-job grain seeds independently.

Project/version settings control delivery subfolders. Native task/source prefixes
and counters remain. PNG metadata records the workflow/prompt and delivery recipe.

## Drafts and Quality promotion

Quality uses the base model and its selected adapters/guidance. Draft lazily loads
the named Viggle v0.2.1 merged checkpoint and uses six Euler steps with the matching
resolution-shifted sigmas. It bypasses Quality LoRAs/ControlNet. These are separate
model recipes, not a step-count toggle on one checkpoint.

Queue draft renders one draft. Explore 4 drafts queues separate jobs with
incrementing shared seeds. To promote a selected result, restore that draft's PNG
workflow, then Queue quality. Source, instruction and seed are restored; composition
can change when the base model rerenders. API-only PNGs carry API graphs rather
than the complete studio canvas.

Only the previous transformer family is explicitly unloaded when switching
Quality/Draft. CLIP, VAE and upscaler residency remains managed by ComfyUI.
The previous Quality model is tracked weakly; Draft CPU ownership is released on
promotion. A single shared native AI-upscaler descriptor avoids repeated weight
loading across finishing nodes and folder items.

## Previews and re-finishing

Preview mask/layout only queues the supported active-task preview dependencies.
Edit, Masked Edit and Upscale Single have previews. It excludes Qwen sampling, AI
upscaling, grain and final saves. Layout previews are capped at 768 pixels.

To change delivery without regenerating, load a raw PNG in Upscale Single or
Upscale Folder. Set the new size, framing, alpha and grain recipe, then queue.
Raw saves precede restoration/compositing/finishing; treat them accordingly.

## Precision

The companion processing nodes resize/composite in floating point, including
premultiplied-alpha handling where applicable. Final PNGs are 8-bit. This is not
an EXR, HDR or color-managed finishing system. No attention backend promises
identical pixels or universal fidelity for faces, text or all edit instructions.
