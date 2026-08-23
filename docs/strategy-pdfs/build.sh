#!/usr/bin/env bash
# Render the strategy documents to PDF with headless Chrome.
# Vector output, no extra dependencies. Re-run after editing the HTML.
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
render() {
  "$CHROME" --headless --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="$2" "file://$PWD/$1" >/dev/null 2>&1
  echo "$2  —  $(python3 -c "import re,sys;d=open('$2','rb').read();print(len(re.findall(rb'/Type\s*/Page[^s]',d)),'pages,',len(d)//1024,'KB')")"
}
render pdf1.html MEMESCOPE_PROJECT_AND_DEFAULT_STRATEGY.pdf
render pdf2.html KARTHIK_PAPER_WALLET_STRATEGY.pdf
