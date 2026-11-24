document.addEventListener("htmx:configRequest", (event) => {
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (token) event.detail.headers["X-CSRF-Token"] = token;
});

document.addEventListener("change", (event) => {
  const checkbox = event.target;
  if (!(checkbox instanceof HTMLInputElement) || checkbox.name !== "checked") return;
  const summary = document.getElementById("selection-summary");
  if (!summary) return;

  const previous = checkbox.dataset.serverChecked === "true";
  const current = checkbox.checked;
  const count = Number(summary.dataset.count || 0) + Number(current) - Number(previous);
  const bytes = Number(summary.dataset.size || 0)
    + (current ? Number(checkbox.dataset.size || 0) : 0)
    - (previous ? Number(checkbox.dataset.size || 0) : 0);
  summary.dataset.count = String(count);
  summary.dataset.size = String(bytes);
  summary.querySelector("span:first-child strong").textContent = String(count);
  summary.querySelector("span:nth-child(2) strong").textContent = formatSize(bytes);
  checkbox.dataset.serverChecked = String(current);
});

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

document.addEventListener("htmx:afterRequest", (event) => {
  const target = event.detail.target;
  if (target?.id !== "selection-summary" || !event.detail.xhr.responseText.includes("text-danger")) return;
  const checkbox = event.detail.elt.querySelector('input[name="checked"]');
  if (checkbox) {
    checkbox.checked = !checkbox.checked;
    checkbox.dataset.serverChecked = String(checkbox.checked);
  }
});

document.addEventListener("error", (event) => {
  const image = event.target;
  if (
    image instanceof HTMLImageElement
    && (image.classList.contains("thumbnail") || image.classList.contains("photo-thumbnail"))
  ) {
    image.hidden = true;
    const fallback = image.nextElementSibling;
    if (fallback) fallback.hidden = false;
  }
}, true);

document.querySelectorAll('input[name="checked"]').forEach((checkbox) => {
  checkbox.dataset.serverChecked = String(checkbox.checked);
});
