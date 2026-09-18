#include <cstdio>
#include <cstdlib>
#include <cstring>

// An HTML visualization -- the third thing a visualizer can produce, after an
// image (problem A, two SVGs) and a file the panel has no viewer for
// (`ascii.cpp`, still on the `samples` group).
//
// HTML is the case with the most constraints on it, and they all come from
// where it ends up rather than from rbx:
//
//   * The gallery draws it in an `<iframe sandbox="">`, so the page gets NO
//     script execution. Everything here is static markup and CSS.
//   * That frame is 140px tall and shows the top-left of the page at full
//     scale -- it is not scaled down. So the headline band is sized to fit in
//     140px on its own, and everything below it is detail for the full-size
//     view you get by opening the file.
//   * The frame has no access to the panel's stylesheet, so VS Code's theme
//     variables are unavailable. `prefers-color-scheme` is what crosses the
//     boundary, and both palettes are defined below.
//   * Nothing may be fetched: no CDN, no web font, no external image. The
//     apples are one inline `<symbol>` reused by `<use>`, which keeps a
//     hundred of them at a hundred bytes each.
//
// Invoked as `vis <visualization.html> <input.txt> [<answer.txt>] [-i]`.
// The answer file is the model solution's output, when rbx has one; it is used
// here to print the total, which is the flow worth demonstrating -- a
// visualizer that reads only the input can never draw what the problem is
// actually about.

namespace {

// rbx appends `-i` when the visualizer runs interactively from `rbx ui`. This
// one writes the same file either way -- rbx then opens it in the browser --
// so flags are skipped rather than handled.
bool is_flag(const char *arg) { return arg != nullptr && arg[0] == '-'; }

void emit_apples(FILE *out, long long count, const char *classes) {
  std::fprintf(out, "<div class=\"%s\">", classes);
  for (long long i = 0; i < count; i++) {
    std::fprintf(out, "<svg class=\"apple\" viewBox=\"0 0 24 24\" role=\"img\" "
                      "aria-label=\"apple\"><use href=\"#apple\"/></svg>");
  }
  std::fprintf(out, "</div>");
}

}  // namespace

int main(int argc, char *argv[]) {
  const char *dest = nullptr;
  const char *paths[3] = {nullptr, nullptr, nullptr};
  int seen = 0;
  for (int i = 1; i < argc; i++) {
    if (is_flag(argv[i])) {
      continue;
    }
    if (dest == nullptr) {
      dest = argv[i];
      continue;
    }
    if (seen < 3) {
      paths[seen++] = argv[i];
    }
  }
  const char *input_path = paths[0];
  const char *answer_path = paths[1];

  if (dest == nullptr || input_path == nullptr) {
    std::fprintf(stderr, "usage: baskets <visualization.html> <input> [answer]\n");
    return 1;
  }

  FILE *in = std::fopen(input_path, "r");
  if (in == nullptr) {
    std::fprintf(stderr, "baskets: cannot read input %s\n", input_path);
    return 1;
  }
  long long a = 0, b = 0;
  if (std::fscanf(in, "%lld %lld", &a, &b) != 2) {
    std::fclose(in);
    std::fprintf(stderr, "baskets: input is not two integers\n");
    return 1;
  }
  std::fclose(in);

  // The answer, when rbx passed one. Falling back to a+b keeps the page
  // drawable before any solution has run -- `rbx build --visualize` draws the
  // whole testset, and an unbuilt answer must not fail the build.
  long long total = a + b;
  bool from_answer = false;
  if (answer_path != nullptr) {
    FILE *ans = std::fopen(answer_path, "r");
    if (ans != nullptr) {
      long long parsed = 0;
      if (std::fscanf(ans, "%lld", &parsed) == 1) {
        total = parsed;
        from_answer = true;
      }
      std::fclose(ans);
    }
  }

  // Run as the SOLUTION visualizer, that third file is what a solution
  // printed, not the jury's answer -- so it can be wrong, and a page that just
  // drew it as "the total" would hide exactly the bug the visualizer exists to
  // show. Disagreement with a + b is called out instead.
  const bool disagrees = from_answer && total != a + b;

  FILE *out = std::fopen(dest, "w");
  if (out == nullptr) {
    std::fprintf(stderr, "baskets: cannot write %s\n", dest);
    return 1;
  }

  std::fprintf(out, R"HTML(<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>apples &middot; %lld + %lld</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #fbfaf7;
    --panel: #ffffff;
    --ink: #1c1917;
    --dim: #78716c;
    --line: #e7e2da;
    --apple-a: #e04b3c;
    --apple-b: #e8a13a;
    --leaf: #4f9d5d;
    --accent: #b91c1c;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17181c;
      --panel: #1f2127;
      --ink: #f2f0ec;
      --dim: #a1a1aa;
      --line: #2e3038;
      --apple-a: #f0685a;
      --apple-b: #f0b45c;
      --leaf: #6dbf7c;
      --accent: #f0685a;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body {
    background: var(--bg);
    color: var(--ink);
    font: 14px/1.45 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI",
          Roboto, "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }

  /* The headline band is 140px tall on purpose: that is exactly the height of
     a gallery cell, so the thumbnail shows this and nothing half-cut. */
  .band {
    height: 140px;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 6px;
    overflow: hidden;
    border-bottom: 1px solid var(--line);
    background: var(--panel);
  }
  .eyebrow {
    font-size: 11px;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--dim);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* A gallery cell is as narrow as 180px and the frame does not scale the page
     down, so the headline is sized in `vw` and clamped: it fills a full-size
     window and still fits, unclipped, in the narrowest cell the grid makes. */
  .eq {
    display: flex;
    align-items: baseline;
    gap: .22em;
    font-size: clamp(18px, 8.5vw, 40px);
    font-weight: 650;
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
    flex-wrap: wrap;
  }
  .eq .op { font-size: .65em; font-weight: 400; color: var(--dim); }
  /* The result is one flex item, so a narrow cell wraps `= 100` as a unit
     instead of leaving a lone `=` hanging off the first line. */
  .eq .res { display: flex; align-items: baseline; gap: .22em; }
  .eq .a { color: var(--apple-a); }
  .eq .b { color: var(--apple-b); }
  .eq .sum { color: var(--ink); }
  .eq .sum.off { color: var(--accent); }
  .note { font-size: 12px; color: var(--dim); }
  .note.off { color: var(--accent); font-weight: 600; }

  /* One clipped row of the real thing, so the thumbnail is a picture and not
     just a caption. `nowrap` + `hidden`: whatever does not fit is cut at the
     frame edge rather than pushing the note out of the band. */
  .strip {
    display: flex;
    flex-wrap: nowrap;
    gap: 3px;
    overflow: hidden;
    height: 18px;
  }
  .strip .apple { width: 18px; height: 18px; flex: 0 0 auto; }
  .strip.a { color: var(--apple-a); }
  .strip.b { color: var(--apple-b); }
  .strips { display: flex; gap: 6px; overflow: hidden; }

  /* Below a gallery cell's width there is room for the sum or for the caption,
     not both. The sum is the visualization; the caption explains where one
     number came from, and it is still there when the file is opened. */
  @media (max-width: 340px) {
    .band { padding: 10px 12px; }
    .note { display: none; }
  }

  .baskets { padding: 18px; display: grid; gap: 14px; }
  .basket {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 12px 14px 14px;
  }
  .basket h2 {
    margin: 0 0 10px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--dim);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .tally {
    font-size: 13px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--ink);
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 1px 8px;
  }
  .grid { display: flex; flex-wrap: wrap; gap: 4px; }
  /* `fill`, not a descendant rule: the markup a `<use>` clones lives in a
     shadow tree that outer selectors cannot reach. Only inherited properties
     cross that boundary, so the body takes its colour from `fill` here and the
     leaf carries its own presentation attribute in the symbol below. */
  .apple { width: 22px; height: 22px; fill: currentColor; }
  .grid.a .apple { color: var(--apple-a); }
  .grid.b .apple { color: var(--apple-b); }
  .total { display: flex; align-items: baseline; gap: 8px; }
  .total strong { font-size: 20px; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<svg width="0" height="0" aria-hidden="true" style="position:absolute">
  <symbol id="apple" viewBox="0 0 24 24">
    <path d="M11.9 7.1c-.3-1.4-.2-2.6.4-3.6" fill="none" stroke="#4f9d5d" stroke-width="1.4" stroke-linecap="round"/>
    <path d="M12.7 6.4c.3-2 1.9-3.4 3.9-3.5-.1 2-1.8 3.5-3.9 3.5z" fill="#4f9d5d"/>
    <path d="M12 8c1.7-1.5 4.1-1.6 5.7 0 1.9 1.9 1.8 5.4.2 8-1 1.7-2.4 3.1-3.7 3.1-.8 0-1.4-.4-2.2-.4s-1.4.4-2.2.4c-1.3 0-2.7-1.4-3.7-3.1-1.6-2.6-1.7-6.1.2-8C7.9 6.4 10.3 6.5 12 8z"/>
  </symbol>
</svg>
<div class="band">
  <div class="eyebrow">apples</div>
  <div class="eq">
    <span class="n a">%lld</span><span class="op">+</span>
    <span class="n b">%lld</span>
    <span class="res"><span class="op">=</span><span class="n sum%s">%lld</span></span>
  </div>
  <div class="strips">
)HTML",
               a, b, a, b, disagrees ? " off" : "", total);

  // The strip is generated, so it closes the raw block above rather than
  // living inside it.
  emit_apples(out, a, "strip a");
  emit_apples(out, b, "strip b");

  std::fprintf(out, R"HTML(</div>
  <div class="note%s">%s</div>
</div>
<div class="baskets">
)HTML",
               disagrees ? " off" : "",
               disagrees ? "the file says this, but the baskets hold "
                           "a + b &mdash; look at the solution"
               : from_answer ? "total read from the answer file"
                             : "no answer file yet &mdash; total computed from "
                               "the input");

  std::fprintf(out,
               "<section class=\"basket\"><h2>Basket A<span "
               "class=\"tally\">%lld</span></h2>",
               a);
  emit_apples(out, a, "grid a");
  std::fprintf(out, "</section>");

  std::fprintf(out,
               "<section class=\"basket\"><h2>Basket B<span "
               "class=\"tally\">%lld</span></h2>",
               b);
  emit_apples(out, b, "grid b");
  std::fprintf(out, "</section>");

  // a + b, not the number read from the file: the baskets below are drawn from
  // the input, and the tally has to count what is drawn.
  std::fprintf(out,
               "<section class=\"basket\"><h2>Together<span "
               "class=\"tally\">%lld</span></h2><div class=\"total\"><strong>%lld"
               "</strong><span class=\"note\">apples in one basket</span></div>",
               a + b, a + b);
  emit_apples(out, a, "grid a");
  emit_apples(out, b, "grid b");
  std::fprintf(out, "</section>");

  std::fprintf(out, "</div>\n</body>\n</html>\n");
  std::fclose(out);
  return 0;
}
