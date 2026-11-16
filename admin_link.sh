#!/bin/bash
# Kiírja a Tanoda admin-oldal teljes linkjét (a titkos kulccsal) – csak a saját terminálodban futtasd, ne oszd meg.
cd "$(dirname "$0")" || exit 1
echo "Tanoda admin (tailnetről, telefonról/laptopról):"
echo "https://kisfonok.tail4d6ec9.ts.net:8443/admin?k=$(cat .admin_token)"
echo
echo "Itthon, a laptopon:  http://localhost:8090/admin?k=$(cat .admin_token)"
