import { betterAuth } from "better-auth";
import { prismaAdapter } from "better-auth/adapters/prisma";
import prisma from "@/lib/prisma";
import { nextCookies } from "better-auth/next-js";
import { scryptAsync } from "@noble/hashes/scrypt.js";
import { hex } from "@better-auth/utils/hex";
import { hexToBytes } from "@noble/hashes/utils.js";
import { constantTimeEqual } from "better-auth/crypto";

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

// Custom password hashing with reduced scrypt parameters for Bun performance.
// Default Better Auth uses N=16384, r=16, p=1 which takes ~45s in Bun.
// These reduced parameters (N=4096, r=8, p=1) are still secure for most use cases
// and complete in under 1 second.
const scryptConfig = {
  N: 4096,
  r: 8,
  p: 1,
  dkLen: 64,
};

async function generateKey(password: string, salt: string): Promise<Uint8Array> {
  return await scryptAsync(password.normalize("NFKC"), salt, {
    N: scryptConfig.N,
    p: scryptConfig.p,
    r: scryptConfig.r,
    dkLen: scryptConfig.dkLen,
    maxmem: 128 * scryptConfig.N * scryptConfig.r * 2,
  });
}

const customHashPassword = async (password: string): Promise<string> => {
  const salt = hex.encode(crypto.getRandomValues(new Uint8Array(16)));
  const key = await generateKey(password, salt);
  return `${salt}:${hex.encode(key)}`;
};

const customVerifyPassword = async ({
  hash,
  password,
}: {
  hash: string;
  password: string;
}): Promise<boolean> => {
  const [salt, key] = hash.split(":");
  if (!salt || !key) throw new Error("Invalid password hash");
  return constantTimeEqual(await generateKey(password, salt), hexToBytes(key));
};

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
      hash: customHashPassword,
      verify: customVerifyPassword,
    },
  },
  socialProviders: {
    google: {
      clientId: process.env.GOOGLE_CLIENT_ID as string,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET as string,
    },
  },
  plugins: [
    nextCookies(), // Enable Next.js cookie handling
  ],
});

export type Session = typeof auth.$Infer.Session;
