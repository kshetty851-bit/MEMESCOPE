#!/usr/bin/env bash
# Screenshot each .page section at exact A4 pixel size for visual QA.
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRC="$1"; PREFIX="$2"; N="$3"
for i in $(seq 1 "$N"); do
  cat > "qa/_v$i.html" <<HTML
<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="../style.css">
<style>html,body{background:#05070f}
.page{page-break-after:auto}
.page:not(:nth-of-type($i)){display:none}</style>
</head><body>
HTML
  sed -n '/<body>/,/<\/body>/p' "$SRC" | sed '1d;$d' >> "qa/_v$i.html"
  echo '</body></html>' >> "qa/_v$i.html"
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --window-size=794,1123 --force-device-scale-factor=2 \
    --screenshot="qa/${PREFIX}_p${i}.png" "file://$PWD/qa/_v$i.html" >/dev/null 2>&1
done
rm -f qa/_v*.html
ls -la qa/${PREFIX}_p*.png | awk '{print $NF, $5"B"}'
