#!/usr/bin/env bun
/**
 * ensure-local-admin.mjs
 *
 * Local beta bootstrap for Better Auth admin login.
 *
 * Safe behavior:
 * - Refuses to mutate unless VIRACLIP_LOCAL_AUTH_BOOTSTRAP=true
 * - Creates or repairs admin@viraclip.com (or the configured admin email)
 * - Ensures emailVerified=true and admin/beta flags are enabled
 * - Ensures a credential account exists with a Better Auth compatible password hash
 * - Never prints the plaintext password
 */

import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { hashPassword } from "better-auth/crypto";
import { PrismaClient } from "../src/generated/prisma/index.js";

const isTrue = (value) => ["1", "true", "yes", "on"].includes(String(value ?? "").trim().toLowerCase());
const bootstrapEnabled = isTrue(process.env.VIRACLIP_LOCAL_AUTH_BOOTSTRAP);
const adminEmail = process.env.VIRACLIP_LOCAL_ADMIN_EMAIL || "admin@viraclip.com";
const adminPassword = process.env.VIRACLIP_LOCAL_ADMIN_PASSWORD || "";
const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRootCandidates = [resolve(scriptDir, "..", ".."), resolve(scriptDir, "..")];
const repoRoot =
  repoRootCandidates.find((candidate) =>
    existsSync(resolve(candidate, "frontend", "src", "generated", "prisma", "index.js")) ||
    existsSync(resolve(candidate, "src", "generated", "prisma", "index.js"))
  ) || resolve(scriptDir, "..", "..");
const markerPath = resolve(repoRoot, "outputs", "generated", "_auth_bootstrap", "local_admin_state.json");

function normalizeName(email) {
  const local = String(email || "").split("@")[0] || "admin";
  return local
    .replace(/[._-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase()) || "Admin";
}

function safeBool(value) {
  return value ? "true" : "false";
}

async function writeMarker(payload) {
  const normalized = {
    ...payload,
    admin_email: adminEmail,
    timestamp: new Date().toISOString(),
  };
  await mkdir(dirname(markerPath), { recursive: true });
  await writeFile(markerPath, `${JSON.stringify(normalized, null, 2)}\n`, "utf8");
}

async function main() {
  if (!bootstrapEnabled) {
    await writeMarker({
      status: "skipped",
      active: false,
      user_created: false,
      account_created: false,
      password_updated: false,
      reason: "VIRACLIP_LOCAL_AUTH_BOOTSTRAP_not_true",
    });
    console.log("LOCAL_AUTH_BOOTSTRAP=SKIPPED");
    console.log(`admin_email=${adminEmail}`);
    console.log("reason=VIRACLIP_LOCAL_AUTH_BOOTSTRAP_not_true");
    return 0;
  }

  if (!adminPassword) {
    await writeMarker({
      status: "warn",
      active: false,
      user_created: false,
      account_created: false,
      password_updated: false,
      reason: "password_missing",
    });
    console.log("LOCAL_AUTH_BOOTSTRAP=WARN");
    console.log(`admin_email=${adminEmail}`);
    console.log("reason=password_missing");
    console.log("user_created=false");
    console.log("account_created=false");
    console.log("password_updated=false");
    console.log("active=false");
    return 0;
  }

  const prisma = new PrismaClient();
  try {
    const now = new Date();
    const passwordHash = await hashPassword(adminPassword);

    let userCreated = false;
    let accountCreated = false;
    let passwordUpdated = false;
    let user = await prisma.$transaction(async (tx) => {
      let currentUser = await tx.user.findUnique({ where: { email: adminEmail } });

      if (!currentUser) {
        currentUser = await tx.user.create({
          data: {
            id: randomUUID(),
            name: normalizeName(adminEmail),
            email: adminEmail,
            emailVerified: true,
            image: null,
            first_name: "Admin",
            last_name: "User",
            password_hash: passwordHash,
            beta_access: true,
            is_admin: true,
            waitlist_status: "approved",
          },
        });
        userCreated = true;
      } else {
        const updates = {
          emailVerified: true,
          is_admin: true,
          beta_access: true,
          waitlist_status: "approved",
          password_hash: passwordHash,
          name: currentUser.name?.trim() ? currentUser.name : normalizeName(adminEmail),
        };
        currentUser = await tx.user.update({ where: { id: currentUser.id }, data: updates });
      }

      const credentialAccount = await tx.account.findFirst({
        where: {
          userId: currentUser.id,
          providerId: "credential",
        },
      });

      if (!credentialAccount) {
        await tx.account.create({
          data: {
            id: randomUUID(),
            accountId: currentUser.id,
            providerId: "credential",
            userId: currentUser.id,
            password: passwordHash,
            createdAt: now,
            updatedAt: now,
          },
        });
        accountCreated = true;
        passwordUpdated = true;
      } else {
        await tx.account.update({
          where: { id: credentialAccount.id },
          data: {
            accountId: credentialAccount.accountId || currentUser.id,
            providerId: "credential",
            userId: currentUser.id,
            password: passwordHash,
            updatedAt: now,
          },
        });
        passwordUpdated = true;
      }

      return currentUser;
    });

    console.log("LOCAL_AUTH_BOOTSTRAP=PASS");
    console.log(`admin_email=${adminEmail}`);
    console.log(`user_created=${safeBool(userCreated)}`);
    console.log(`account_created=${safeBool(accountCreated)}`);
    console.log(`password_updated=${safeBool(passwordUpdated)}`);
    console.log("active=true");
    await writeMarker({
      status: "pass",
      active: true,
      user_created: userCreated,
      account_created: accountCreated,
      password_updated: passwordUpdated,
      email_verified: true,
      is_admin: true,
      beta_access: true,
      waitlist_status: "approved",
    });
    return 0;
  } catch (error) {
    try {
      await writeMarker({
        status: "fail",
        active: false,
        user_created: false,
        account_created: false,
        password_updated: false,
        reason: error instanceof Error ? error.message : String(error),
      });
    } catch {
      // Ignore marker write failures; the bootstrap error is already reported.
    }
    console.log("LOCAL_AUTH_BOOTSTRAP=FAIL");
    console.log(`admin_email=${adminEmail}`);
    console.log(`reason=${error instanceof Error ? error.message : String(error)}`);
    return 1;
  } finally {
    await prisma.$disconnect();
  }
}

const exitCode = await main();
process.exit(exitCode);
