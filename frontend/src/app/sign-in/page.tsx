import { SignIn } from "@/components/auth/sign-in";
import Link from "next/link";

export default function SignInPage() {
  return (
    <div
      className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8"
      style={{ background: "var(--bg)" }}
    >
      <div className="max-w-md w-full space-y-8">
        <SignIn />
        <div className="text-center">
          <p className="text-sm" style={{ color: "var(--meta)" }}>
            Don't have an account?{" "}
            <Link
              href="/sign-up"
              className="font-medium transition-all"
              style={{ color: "var(--accent)" }}
            >
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
