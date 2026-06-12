/**
 * reset-admin-password.ts
 *
 * Safely resets the password for admin@viraclip.com using the exact same
 * hashing mechanism that Better Auth uses internally (scrypt via
 * node:crypto with N=16384, r=16, p=1, dkLen=64).
 *
 * This version uses ONLY Node.js built-in modules (crypto, util) so it
 * works inside the production standalone container where @better-auth/utils
 * is not available.
 *
 * Usage (inside the frontend container):
 *   node /app/scripts/reset-admin-password.mjs
 *
 * Environment variables:
 *   DATABASE_URL   – Prisma connection string (already set in the container)
 *   ADMIN_EMAIL    – defaults to "admin@viraclip.com"
 *   ADMIN_PASSWORD – defaults to "admin123" (override for production)
 */

import { randomBytes, scrypt } from "node:crypto";
import { promisify } from "node:util";

const scryptAsync = promisify(scrypt);

const config = {
  N: 16384,
  r: 16,
  p: 1,
  dkLen: 64,
};

/**
 * Hash a password using the exact same scrypt parameters as Better Auth.
 * Output format: "salt_hex:derived_key_hex"
 */
async function hashPassword(password) {
  const salt = randomBytes(16).toString("hex");
  const key = await scryptAsync(
    password.normalize("NFKC"),
    salt,
    config.dkLen,
    {
      N: config.N,
      r: config.r,
      p: config.p,
      maxmem: 128 * config.N * config.r * 2,
    }
  );
  return `${salt}:${key.toString("hex")}`;
}

// ---------------------------------------------------------------------------
// Prisma setup – we import from the generated client in the standalone build.
// The production container has @prisma/client available.
// ---------------------------------------------------------------------------
import { PrismaClient } from "../src/generated/prisma/index.js";

const prisma = new PrismaClient();

async function main() {
  const email = process.env.ADMIN_EMAIL || "admin@viraclip.com";
  const password = process.env.ADMIN_PASSWORD || "admin123";

  // 1. Find user
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user) {
    console.error(`✗ usuario NO encontrado: ${email}`);
    process.exit(1);
  }
  console.log(`✓ usuario encontrado: ${user.email} (id=${user.id})`);

  // 2. Find credential account
  const account = await prisma.account.findFirst({
    where: { userId: user.id, providerId: "credential" },
  });
  if (!account) {
    console.error(`✗ credential account NO encontrado para ${email}`);
    process.exit(1);
  }
  console.log(`✓ credential account encontrado: id=${account.id}`);

  // 3. Hash the password using the same scrypt parameters as Better Auth
  //    (N=16384, r=16, p=1, dkLen=64) with a random 16-byte salt.
  //    Output format: "salt_hex:derived_key_hex"
  const hashed = await hashPassword(password);

  // 4. Update only the password field
  await prisma.account.update({
    where: { id: account.id },
    data: { password: hashed },
  });

  console.log(`✓ password actualizado`);
  console.log(`  length nuevo del hash: ${hashed.length}`);
}

main()
  .catch((err) => {
    console.error("Fatal error:", err);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
