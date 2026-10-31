// SPDX-License-Identifier: GPL-3.0-only
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

function widget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

async function queueMode(node, value, count = 1) {
  const w = widget(node, "mode");
  w.value = value;
  w.callback?.(value);
  app.graph.setDirtyCanvas(true, true);
  // Comfy's queue owns control-after-generate and per-job workflow metadata.
  await app.queuePrompt(0, count);
}

async function queuePreviews() {
  const prompt = await app.graphToPrompt();
  const selected = new Set(Object.entries(prompt.output)
    .filter(([, node]) => node.class_type === "PreviewImage" && node._meta?.title?.startsWith("Preview ·"))
    .map(([id]) => id));
  if (!selected.size) {
    throw new Error("Select Edit, Masked Edit, or Upscale Single to preview masks/layout.");
  }
  const keep = new Set();
  function visit(id) {
    if (keep.has(id)) return;
    keep.add(id);
    for (const value of Object.values(prompt.output[id]?.inputs ?? {})) {
      if (Array.isArray(value) && value.length === 2 && typeof value[0] === "string" && prompt.output[value[0]]) visit(value[0]);
    }
  }
  selected.forEach(visit);
  const output = Object.fromEntries(Object.entries(prompt.output).filter(([id]) => keep.has(id)));
  await api.queuePrompt(0, { output, workflow: prompt.workflow });
}

app.registerExtension({
  name: "QwenStudio.EditDeliveryDraft",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!["QwenStudioRenderMode", "QwenStudioDeliveryPreset"].includes(nodeData.name)) return;
    const previous = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      previous?.apply(this, arguments);
      const action = (label, callback) => this.addWidget("button", label, null,
        () => Promise.resolve(callback()).catch((e) => app.extensionManager.toast.add({ severity: "error", summary: "Luminaire Edit Studio", detail: String(e.message ?? e), life: 8000 })),
        { serialize: false });
      if (nodeData.name === "QwenStudioRenderMode") {
        action("Queue draft", () => queueMode(this, "Draft - Viggle 6-step"));
        action("Explore 4 drafts · increment seed", async () => {
          const seed = app.graph._nodes.find((n) => n.properties?.studio_role === "seed");
          if (!seed) throw new Error("Studio seed control was not found.");
          const control = widget(seed, "control_after_generate");
          if (!control) throw new Error("The seed control has no increment option.");
          const saved = control.value;
          control.value = "increment";
          try { await queueMode(this, "Draft - Viggle 6-step", 4); }
          finally { control.value = saved; }
        });
        action("Queue quality · current inputs and seed", () => queueMode(this, "Quality"));
      }
      action("Preview mask/layout only", queuePreviews);
    };
  },
});
