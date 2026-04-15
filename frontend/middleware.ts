import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_FILE = /\.(.*)$/;

// Public routes that don't require authentication
const PUBLIC_ROUTES = [
  "/",
  "/sign-in",
  "/sign-up",
  "/api/auth",
];

// Protected routes that require beta access
const BETA_PROTECTED_ROUTES = [
  "/dashboard",
  "/tasks",
  "/list",
  "/settings",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Landing-only mode check (existing functionality)
  const isLandingOnlyModeEnabled =
    process.env.NEXT_PUBLIC_LANDING_ONLY_MODE === "true";

  if (isLandingOnlyModeEnabled) {
    if (
      pathname === "/" ||
      pathname.startsWith("/_next") ||
      pathname.startsWith("/api/billing/webhook") ||
      PUBLIC_FILE.test(pathname)
    ) {
      return NextResponse.next();
    }

    if (pathname.startsWith("/api")) {
      return NextResponse.json(
        { error: "ViraClip is in landing-page-only mode." },
        { status: 503 }
      );
    }

    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  // Allow public files and Next.js internals
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/auth") ||
    PUBLIC_FILE.test(pathname)
  ) {
    return NextResponse.next();
  }

  // Allow public routes
  if (PUBLIC_ROUTES.some(route => pathname === route || pathname.startsWith(route))) {
    return NextResponse.next();
  }

  // Note: Better-auth handles session verification in server components
  // This middleware only handles route protection
  // Actual auth check happens in layout.tsx using auth.api.getSession()

  return NextResponse.next();
}

export const config = {
  matcher: "/:path*",
};
