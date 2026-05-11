import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

  // Extract user_id from request headers
  const userId =
    request.headers.get("user_id") ??
    request.headers.get("x-viraclip-user-id") ??
    "local-test-user";

  try {
    const formData = await request.formData();
    const file = formData.get("file");
    const processingMode = formData.get("processing_mode") ?? "fast";

    if (!file || !(file instanceof File)) {
      return NextResponse.json(
        { detail: "No file provided" },
        { status: 400 }
      );
    }

    // Forward to backend
    const backendFormData = new FormData();
    backendFormData.append("file", file);
    backendFormData.append("processing_mode", processingMode as string);

    const backendRes = await fetch(`${backendUrl}/upload`, {
      method: "POST",
      headers: {
        user_id: userId,
      },
      body: backendFormData,
    });

    const body = await backendRes.json();

    if (!backendRes.ok) {
      return NextResponse.json(body, { status: backendRes.status });
    }

    return NextResponse.json(body);
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Internal server error";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
