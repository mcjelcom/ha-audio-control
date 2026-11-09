#!/usr/bin/env bash
# Render docs/diagrams/*.puml -> docs/assets/diagrams/*.svg with a PINNED,
# checksum-verified PlantUML (MIT build). Rendering happens here and in CI --
# never via an external PlantUML server at page-view time.
#
#   scripts/render-diagrams.sh          render
#   scripts/render-diagrams.sh --check  fail if committed SVGs are out of date
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=1.2026.9
SHA256=835b2f2eb1d756da3f03bffdbd0baf252b4b858547a741ac8e972958a09c7f91
JAR="${PLANTUML_CACHE:-$HOME/.cache/plantuml}/plantuml-mit-$VERSION.jar"

if [ ! -f "$JAR" ]; then
  mkdir -p "$(dirname "$JAR")"
  # -f: an HTTP error (e.g. GitHub's 504 on 2026-11-09) fails here as a download
  # error instead of saving the error page and failing the checksum; retries ride
  # out short outages.
  curl -fsSL --retry 5 --retry-delay 15 --retry-all-errors -o "$JAR" \
    "https://github.com/plantuml/plantuml/releases/download/v$VERSION/plantuml-mit-$VERSION.jar" \
    || { rm -f "$JAR"; echo "PlantUML download failed (GitHub unavailable?) -- retry later" >&2; exit 1; }
fi
echo "$SHA256  $JAR" | shasum -a 256 -c - >/dev/null \
  || { rm -f "$JAR"; echo "PlantUML checksum mismatch -- the downloaded file is not the pinned release" >&2; exit 1; }

OUT=docs/assets/diagrams
if [ "${1:-}" = "--check" ]; then
  OUT=$(mktemp -d)
fi
# One file per run, each time-bounded: a single invocation over all files with
# -failfast2 hung indefinitely. -nometadata keeps the output reproducible.
OUT_ABS="$(cd "$OUT" && pwd)"
for src in docs/diagrams/*.puml; do
  timeout 60 java -Djava.awt.headless=true -jar "$JAR" -tsvg -nometadata \
    -o "$OUT_ABS" "$src" || { echo "failed to render $src" >&2; exit 1; }
done

if [ "${1:-}" = "--check" ]; then
  stale=0
  for f in "$OUT"/*.svg; do
    if ! cmp -s "$f" "docs/assets/diagrams/$(basename "$f")"; then
      echo "stale: docs/assets/diagrams/$(basename "$f") -- run scripts/render-diagrams.sh" >&2
      stale=1
    fi
  done
  exit $stale
fi
