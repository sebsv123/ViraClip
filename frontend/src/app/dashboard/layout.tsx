import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { AppShell } from "@/components/app-shell";

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
    <AppShell user={user}>
      {children}
    </AppShell>
  );
}
