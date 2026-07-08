// High-resolution PNG export for Recharts (SVG) charts.
//
// Recharts renders plain <svg>, so we can serialise it, paint it onto a
// canvas scaled up (default 3x → ~288 DPI-equivalent for on-screen charts),
// and download the result as a crisp PNG suitable for a thesis / slides.

const FONT_STACK =
  'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

function sanitize(name) {
  return (name || "chart")
    .toString()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[\s_-]+/g, "-")
    .toLowerCase() || "chart";
}

// Convert one <svg> element to a PNG Blob at the given pixel scale.
// `fontScale` enlarges chart text in the exported image relative to what's on
// screen (1 = same size). Extra padding is added so bigger labels don't clip.
function svgToPngBlob(svg, scale = 3, fontScale = 1.35) {
  return new Promise((resolve, reject) => {
    const rect = svg.getBoundingClientRect();
    const width = Math.max(1, rect.width);
    const height = Math.max(1, rect.height);

    const clone = svg.cloneNode(true);

    // Enlarge every text/tspan by walking the live tree and the clone in
    // parallel (identical structure), reading the resolved on-screen size.
    if (fontScale && fontScale !== 1) {
      const orig = svg.querySelectorAll("text, tspan");
      const copy = clone.querySelectorAll("text, tspan");
      for (let i = 0; i < copy.length; i++) {
        const base = parseFloat(orig[i] && getComputedStyle(orig[i]).fontSize) || 12;
        const fs = `${(base * fontScale).toFixed(1)}px`;
        copy[i].style.fontSize = fs;
        copy[i].setAttribute("font-size", fs);
      }
    }

    // Breathing room so the enlarged axis / value labels are never cut off.
    const padL = 52;
    const padR = 52;
    const padT = 14;
    const padB = 26;
    const vbW = width + padL + padR;
    const vbH = height + padT + padB;

    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", vbW);
    clone.setAttribute("height", vbH);
    clone.setAttribute("viewBox", `${-padL} ${-padT} ${vbW} ${vbH}`);
    clone.style.fontFamily = FONT_STACK;

    // Opaque white background so the PNG isn't transparent.
    const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    bg.setAttribute("x", -padL);
    bg.setAttribute("y", -padT);
    bg.setAttribute("width", vbW);
    bg.setAttribute("height", vbH);
    bg.setAttribute("fill", "#ffffff");
    clone.insertBefore(bg, clone.firstChild);

    const data = new XMLSerializer().serializeToString(clone);
    const url = URL.createObjectURL(
      new Blob([data], { type: "image/svg+xml;charset=utf-8" })
    );

    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(vbW * scale);
      canvas.height = Math.ceil(vbH * scale);
      const ctx = canvas.getContext("2d");
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.drawImage(img, 0, 0, vbW, vbH);
      URL.revokeObjectURL(url);
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("toBlob failed"))),
        "image/png"
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not render SVG to image"));
    };
    img.src = url;
  });
}

function triggerDownload(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename.endsWith(".png") ? filename : `${filename}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Export a single chart. `el` may be the <svg> itself or any element
// containing exactly one chart svg.
export async function exportChartPng(el, filename, scale = 3) {
  if (!el) return;
  // Prefer the Recharts chart surface so we never grab a UI icon <svg>.
  const svg =
    el.classList?.contains("recharts-surface")
      ? el
      : el.querySelector(".recharts-surface") ||
        (el.tagName === "svg" ? el : el.querySelector("svg"));
  if (!svg) return;
  const blob = await svgToPngBlob(svg, scale);
  triggerDownload(blob, sanitize(filename));
}

// Export every chart svg found under `container`, one PNG each.
export async function exportAllChartsPng(container, prefix = "chart", scale = 3) {
  if (!container) return;
  const svgs = Array.from(container.querySelectorAll(".recharts-surface"));
  for (let i = 0; i < svgs.length; i++) {
    const blob = await svgToPngBlob(svgs[i], scale);
    triggerDownload(blob, `${sanitize(prefix)}-${String(i + 1).padStart(2, "0")}`);
    await new Promise((r) => setTimeout(r, 200)); // stagger downloads
  }
}
