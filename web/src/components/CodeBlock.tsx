import { useMemo, useState, type ReactNode } from "react";

const KW = new Set(
  "def return if elif else for while in not and or is import from as None True False lambda continue break pass class try except finally with yield global nonlocal assert raise del".split(" "),
);
const BUILTIN = new Set("abs min max sum len range float int dict list zip enumerate sorted round np math numpy print set tuple any all map filter isinstance".split(" "));
const TOKEN =
  /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\b\d+\.?\d*(?:[eE][+-]?\d+)?\b)|([A-Za-z_]\w*)|([^\sA-Za-z_\d#"']+)/g;

/** Tiny Python highlighter: returns React nodes (no innerHTML). */
export function highlightPython(code: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  let prevWord = "";
  for (const m of code.matchAll(TOKEN)) {
    const i = m.index ?? 0;
    if (i > last) out.push(code.slice(last, i));
    const [tok, com, str, num, word, op] = m;
    let cls = "";
    if (com) cls = "tk-com";
    else if (str) cls = "tk-str";
    else if (num) cls = "tk-num";
    else if (word) {
      if (KW.has(word)) cls = "tk-kw";
      else if (prevWord === "def") cls = "tk-fn";
      else if (BUILTIN.has(word)) cls = "tk-bi";
      else if (code[i + word.length] === "(") cls = "tk-call";
      else if (word === "obs" || word === "self") cls = "tk-self";
      prevWord = word;
    } else if (op) cls = "tk-op";
    out.push(
      cls ? (
        <span key={k++} className={cls}>
          {tok}
        </span>
      ) : (
        tok
      ),
    );
    last = i + tok.length;
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}

export function CodeBlock({ code, maxLines = 14 }: { code: string; maxLines?: number }) {
  const [open, setOpen] = useState(false);
  const lines = code.replace(/\s+$/, "").split("\n");
  const long = lines.length > maxLines;
  const shown = open || !long ? lines.join("\n") : lines.slice(0, maxLines).join("\n");
  const nodes = useMemo(() => highlightPython(shown), [shown]);
  return (
    <div className={`code ${long && !open ? "clipped" : ""}`}>
      <pre>
        <code>{nodes}</code>
      </pre>
      {long && (
        <button className="code-more" onClick={(e) => (e.stopPropagation(), setOpen(!open))}>
          {open ? "collapse" : `+${lines.length - maxLines} lines`}
        </button>
      )}
    </div>
  );
}
