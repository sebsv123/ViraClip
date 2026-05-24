import { SignUp } from "@/components/auth/sign-up";
import Link from "next/link";

export default function SignUpPage() {
  return (
    <div
      className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8"
      style={{ background: "var(--bg)" }}
    >
      <div className="max-w-md w-full space-y-8">
        <SignUp />
        <div className="text-center">
          <p className="text-sm" style={{ color: "var(--meta)" }}>
            Already have an account?{" "}
            <Link
              href="/sign-in"
              className="font-medium transition-all"
              style={{ color: "var(--accent)" }}
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
