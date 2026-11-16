#!/bin/bash
# A Tanoda admin-oldal kulcsának beállítása SAJÁT, könnyen begépelhető kulcsra (a képernyőn nem jelenik meg).
# Futtasd a szerver-laptopon (SSH-terminálban):  ~/agentek/tanoda/uj_admin_kulcs.sh
# Utána az admin-oldal:  https://kisfonok.tail4d6ec9.ts.net:8443/admin?k=A_TE_KULCSOD
cd "$(dirname "$0")" || exit 1
read -rsp "Új admin-kulcs (legalább 16 karakter: betű, szám, kötőjel; pl. harom-szo-es-egy-szam-2026): " a; echo
read -rsp "Még egyszer: " b; echo
if [ "$a" != "$b" ]; then echo "❌ A kettő nem egyezik. Semmi nem változott."; exit 1; fi
if [[ ! "$a" =~ ^[A-Za-z0-9_-]{16,}$ ]]; then echo "❌ Legalább 16 karakter kell, csak betű, szám, kötőjel, aláhúzás. Semmi nem változott."; exit 1; fi
( umask 077; printf '%s' "$a" > .admin_token )
chmod 600 .admin_token
echo "✅ Kész. Az admin-oldal: https://kisfonok.tail4d6ec9.ts.net:8443/admin?k=<a most megadott kulcsod>"
echo "   (újraindítás nem kell)"
