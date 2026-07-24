import type { Metadata } from "next";
import "./globals.css";
import { AuthGate } from "@/components/auth/AuthGate";
import { ShayAuthProvider } from "@/lib/shay-auth";
import { WorkspaceProvider } from "@/lib/workspace";
export const metadata: Metadata = {
  title: "Aryx — A Fortress of Structured Knowledge",
  description:
    "Ask questions over your organisation's knowledge graph. Aryx ingests heterogeneous sources, resolves entities, and answers with citations.",
  icons: { icon: "/aryx-logo.png" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen" suppressHydrationWarning>
        <ShayAuthProvider>
          <WorkspaceProvider>
            <AuthGate>{children}</AuthGate>
          </WorkspaceProvider>
        </ShayAuthProvider>
      </body>
    </html>
  );
}
