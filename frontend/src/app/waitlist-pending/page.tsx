import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { Clock, Mail, CheckCircle, ArrowLeft } from "lucide-react";
import Link from "next/link";

export default async function WaitlistPendingPage() {
  const session = await auth.api.getSession({
    headers: await headers(),
  });

  // If not authenticated, redirect to sign-in
  if (!session) {
    redirect("/sign-in");
  }

  // If already has beta access, redirect to dashboard
  if (session.user.beta_access) {
    redirect("/dashboard");
  }

  const waitlistStatus = session.user.waitlist_status || "pending";
  const statusConfig = {
    pending: {
      icon: Clock,
      color: "amber",
      title: "You're on the Waitlist!",
      description: "Thanks for signing up. We're reviewing applications and will send you an email when you're approved.",
    },
    approved: {
      icon: CheckCircle,
      color: "green",
      title: "You're Approved!",
      description: "Refreshing to grant access...",
    },
    rejected: {
      icon: Mail,
      color: "red",
      title: "Application Under Review",
      description: "We'll get back to you soon via email.",
    },
  };

  const config = statusConfig[waitlistStatus as keyof typeof statusConfig] || statusConfig.pending;
  const Icon = config.icon;

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="max-w-md w-full">
        {/* Card */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 text-center">
          {/* Icon */}
          <div className={`w-20 h-20 mx-auto rounded-full bg-${config.color}-500/10 flex items-center justify-center mb-6`}>
            <Icon className={`w-10 h-10 text-${config.color}-400`} />
          </div>

          {/* Title */}
          <h1 className="text-2xl font-bold text-white mb-3">
            {config.title}
          </h1>

          {/* Description */}
          <p className="text-gray-400 mb-6">
            {config.description}
          </p>

          {/* User info */}
          <div className="bg-gray-800 rounded-lg p-4 mb-6">
            <div className="text-sm text-gray-500 mb-1">Signed in as</div>
            <div className="text-white font-medium">{session.user.email}</div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-cyan-400">~2-3</div>
              <div className="text-xs text-gray-500">Days Wait Time</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="text-2xl font-bold text-purple-400">1,247</div>
              <div className="text-xs text-gray-500">In Queue</div>
            </div>
          </div>

          {/* Info box */}
          <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-4 mb-6">
            <p className="text-sm text-cyan-300">
              💡 <strong>Pro tip:</strong> We prioritize users who share ViraClip on social media. 
              Tweet about us with <code className="bg-gray-800 px-1 rounded">@ViraClip</code> to skip the queue!
            </p>
          </div>

          {/* Actions */}
          <div className="flex flex-col gap-3">
            <Link
              href="/"
              className="flex items-center justify-center gap-2 px-6 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Home
            </Link>
            
            <form action="/api/auth/sign-out" method="POST">
              <button
                type="submit"
                className="w-full px-6 py-3 text-gray-400 hover:text-white transition-colors text-sm"
              >
                Sign Out
              </button>
            </form>
          </div>
        </div>

        {/* Help text */}
        <p className="text-center text-sm text-gray-500 mt-6">
          Questions? Email us at{" "}
          <a href="mailto:beta@viraclip.com" className="text-cyan-400 hover:underline">
            beta@viraclip.com
          </a>
        </p>
      </div>
    </div>
  );
}
