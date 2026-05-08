import { NextResponse } from "next/server";
import { createProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

export const dynamic = "force-dynamic";
export const maxDuration = 300; // 5 minutes for large uploads

export async function POST(request: Request) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Forward the raw multipart form data directly to the backend
  // without parsing it in Next.js (avoids body size limits)
  const upstream = await fetchBackend("/tasks/upload", {
    method: "POST",
    userId: session.user.id,
    body: await request.blob(),
    headers: {
      "Content-Type": request.headers.get("content-type") || "multipart/form-data",
    },
    cache: "no-store",
  });

  return createProxyResponse(upstream);
}
