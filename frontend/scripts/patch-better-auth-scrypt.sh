#!/bin/sh
# patch-better-auth-scrypt.sh
#
# Patches Better Auth's scrypt password hashing to use lower parameters
# when running on Bun (which uses pure-JS scrypt instead of native).
#
# Default: N=16384, r=16  -> ~34s per login on Bun
# Patched: N=8192,  r=8   -> ~146ms per login on Bun
#
# This is safe for local dev. For production, use Node.js instead of Bun
# or increase parameters back to defaults.
#
# Guard: only patches when VIRACLIP_PATCH_BETTER_AUTH_SCRYPT=true
# or VIRACLIP_LOCAL_AUTH_BOOTSTRAP=true (local dev default).

set -e

# Guard: only patch in local/dev beta mode
if [ "${VIRACLIP_PATCH_BETTER_AUTH_SCRYPT:-}" != "true" ] && [ "${VIRACLIP_LOCAL_AUTH_BOOTSTRAP:-}" != "true" ]; then
    echo "PATCH_BETTER_AUTH_SCRYPT=SKIPPED (not in local dev mode)"
    exit 0
fi

PASSWORD_FILE="/app/node_modules/better-auth/dist/crypto/password.mjs"

if [ ! -f "$PASSWORD_FILE" ]; then
    echo "PATCH_BETTER_AUTH_SCRYPT=SKIPPED (password.mjs not found)"
    exit 0
fi

# Check if already patched
if grep -q "N: 8192" "$PASSWORD_FILE" 2>/dev/null; then
    echo "PATCH_BETTER_AUTH_SCRYPT=PASS (already patched)"
    exit 0
fi

# Create backup
cp "$PASSWORD_FILE" "${PASSWORD_FILE}.bak"

# Apply patch: reduce N from 16384 to 8192, r from 16 to 8
sed -i 's/\tN: 16384/\tN: 8192/' "$PASSWORD_FILE"
sed -i 's/\tr: 16/\tr: 8/' "$PASSWORD_FILE"

echo "PATCH_BETTER_AUTH_SCRYPT=PASS"
echo "PATCH: scrypt parameters reduced (N: 16384->8192, r: 16->8)"
echo "PATCH: backup saved to ${PASSWORD_FILE}.bak"
