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
  const session = await auth.api.getSession({
    headers: await headers(),
  });

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
      <DashboardSidebar user={user} />

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <DashboardHeader user={user} />
        
        <main className="flex-1 overflow-y-auto p-6 md:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
