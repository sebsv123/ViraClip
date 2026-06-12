import { auth } from "@/lib/auth";
import { toNextJsHandler } from "better-auth/next-js";

const base = toNextJsHandler(auth.handler);

async function timedPost(request: Request) {
  const t0 = performance.now();
  const res = await base.POST(request);
  const ms = Math.round(performance.now() - t0);
  if (ms > 1000) {
    console.log(`[auth-timing] slow POST ${new URL(request.url).pathname} handler=${ms}ms`);
  }
  return res;
}

export const GET = base.GET;
export const POST = timedPost;
