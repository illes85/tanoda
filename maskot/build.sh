#!/bin/bash
# A 3D kabala (Lapi) összeépítése egyetlen böngészőbarát fájllá: tanoda/web/maskot3d.js
# Egyszeri előkészítés: mkdir ~/tanoda_build && cd ~/tanoda_build && npm init -y && npm i three esbuild
export PATH=$HOME/.local/node/bin:$PATH
cd "$(dirname "$0")" || exit 1
cp lapi.src.js dino.js ~/tanoda_build/
cd ~/tanoda_build && npx esbuild lapi.src.js --bundle --minify --format=esm --outfile="$OLDPWD/../web/maskot3d.js"
