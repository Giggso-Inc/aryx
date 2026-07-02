import type { Metadata } from "next";
import { Inter, Fraunces, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthGate } from "@/components/auth/AuthGate";
import { ShayAuthProvider } from "@/lib/shay-auth";
import { WorkspaceProvider } from "@/lib/workspace";

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
  preload: false,
});

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  weight: ["400", "500", "600"],
  preload: false,
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  preload: false,
});
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
    <html
      lang="en"
      className={`${sans.variable} ${display.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
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
