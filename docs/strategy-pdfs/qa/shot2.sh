#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for i in $(seq 1 "$2"); do
  { echo '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="../style.css">'
    echo "<style>html,body{background:#05070f}.page{page-break-after:auto}.page:not(:nth-of-type($i)){display:none}</style></head><body>"
    sed -n '/<body>/,/<\/body>/p' "$1" | sed '1d;$d'
    echo '</body></html>'; } > "qa/_w$i.html"
  "$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=794,1123 \
    --force-device-scale-factor=2 --screenshot="qa/pdf2_p${i}.png" "file://$PWD/qa/_w$i.html" >/dev/null 2>&1
done
rm -f qa/_w*.html
echo rendered
