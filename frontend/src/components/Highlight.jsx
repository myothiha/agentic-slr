import { useMemo } from "react";

// Combine the compiled highlight patterns into one case-insensitive regex and
// wrap matches in <mark>. Falls back to plain text if patterns are invalid.
function buildRegex(patterns) {
  if (!patterns || patterns.length === 0) return null;
  try {
    return new RegExp(`(${patterns.join("|")})`, "gi");
  } catch {
    return null;
  }
}

export default function Highlight({ text, patterns }) {
  const regex = useMemo(() => buildRegex(patterns), [patterns]);
  if (!text) return null;
  if (!regex) return <>{text}</>;

  const parts = [];
  let last = 0;
  let m;
  regex.lastIndex = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(
      <mark key={`${m.index}-${m[0]}`} className="bg-yellow-200 rounded px-0.5">
        {m[0]}
      </mark>
    );
    last = m.index + m[0].length;
    // Guard against zero-length matches causing an infinite loop.
    if (m.index === regex.lastIndex) regex.lastIndex++;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}
