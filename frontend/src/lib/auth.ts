import { randomBytes, scrypt, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";

import { betterAuth } from "better-auth";
import { prismaAdapter } from "better-auth/adapters/prisma";
import { PrismaClient } from "../generated/prisma";
import { nextCookies } from "better-auth/next-js";

const scryptAsync = promisify(scrypt) as (
  password: string | Buffer,
  salt: string | Buffer,
  keylen: number,
  options: { N: number; r: number; p: number; maxmem: number },
) => Promise<Buffer>;

// Native scrypt replacement for Better Auth's pure-JS implementation, which the
// dev-server bundle executes in ~4s per login. Mirrors the (patched) config in
// better-auth/dist/crypto/password.mjs — N=8192, r=8, p=1, dkLen=64, hash format
// `${hexSalt}:${hexKey}` with the salt consumed as a utf8 string — so every
// existing stored hash keeps verifying.
const SCRYPT_PARAMS = { N: 8192, r: 8, p: 1, maxmem: 128 * 8192 * 8 * 2 };

async function deriveScryptKey(password: string, salt: string): Promise<Buffer> {
  return await scryptAsync(password.normalize("NFKC"), salt, 64, SCRYPT_PARAMS);
}

const prisma = new PrismaClient();
const disableSignUp = ["1", "true", "yes"].includes(
  (process.env.DISABLE_SIGN_UP ?? "").toLowerCase()
);

function toOrigin(value?: string) {
  if (!value) {
    return null;
  }

  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

const trustedOrigins = Array.from(
  new Set(
    [
      toOrigin(process.env.NEXT_PUBLIC_APP_URL),
      toOrigin(process.env.BETTER_AUTH_URL),
      "http://localhost:3000",
      "http://sp.localhost:3000",
    ].filter((origin): origin is string => Boolean(origin))
  )
);

export const auth = betterAuth({
  database: prismaAdapter(prisma, {
    provider: "postgresql",
  }),
  user: {
    additionalFields: {
      is_admin: {
        type: "boolean",
        input: false,
      },
      waitlist_status: {
        type: "string",
        defaultValue: "pending",
        input: false,
      },
      beta_access: {
        type: "boolean",
        defaultValue: false,
        input: false,
      },
      clips_this_month: {
        type: "number",
        defaultValue: 0,
        input: false,
      },
    },
  },
  trustedOrigins,
  emailAndPassword: {
    enabled: true,
    disableSignUp,
    password: {
      hash: async (password) => {
        const salt = randomBytes(16).toString("hex");
        const key = await deriveScryptKey(password, salt);
        return `${salt}:${key.toString("hex")}`;
      },
      verify: async ({ hash, password }) => {
        const [salt, keyHex] = hash.split(":");
        if (!salt || !keyHex) {
          return false;
        }
        const key = await deriveScryptKey(password, salt);
        const expected = Buffer.from(keyHex, "hex");
        return expected.length === key.length && timingSafeEqual(expected, key);
      },
    },
  },
  socialProviders: {
    // Only enable Google OAuth when credentials are configured.
    // Without this guard, Better Auth attempts to initialise the provider
    // with undefined values, which can cause spurious timeouts on login.
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? { google: { clientId: process.env.GOOGLE_CLIENT_ID, clientSecret: process.env.GOOGLE_CLIENT_SECRET } }
      : {}),
  },
  plugins: [
    nextCookies(), // Enable Next.js cookie handling
  ],
});

export type Session = typeof auth.$Infer.Session;
