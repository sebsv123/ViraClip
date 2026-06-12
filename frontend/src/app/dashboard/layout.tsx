import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { DashboardHeader } from "@/components/dashboard/header";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  let session;
  try {
    session = await auth.api.getSession({
      headers: await headers(),
    });
  } catch (err) {
    // If auth/session throws (e.g. DB still booting after restart),
    // redirect safely to sign-in instead of crashing the whole app.
    console.error("DashboardLayout: session fetch failed", err);
    redirect("/sign-in");
  }

  // Redirect if not authenticated
  if (!session) {
    redirect("/sign-in");
  }

  // Check beta access
  const user = session.user;
  if (!user.beta_access) {
    redirect("/waitlist-pending");
  }

  return (
    <div className="flex h-screen bg-gray-950">
      {/* Sidebar */}
      <DashboardSidebar user={user as any} />

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <DashboardHeader user={{ ...user, image: user.image ?? undefined }} />
        
        <main className="flex-1 overflow-y-auto p-6 md:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
