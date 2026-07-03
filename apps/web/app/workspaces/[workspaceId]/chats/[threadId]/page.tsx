import { Header } from "@/components/brand/Header";
import { AuthGuard } from "@/components/shay/AuthGuard";
import { ShayChatSurface } from "@/components/shay/ShayChatSurface";

export default async function Page({
  params,
}: {
  params: Promise<{ workspaceId: string; threadId: string }>;
}) {
  const { workspaceId, threadId } = await params;
  return (
    <AuthGuard>
      <div className="min-h-screen bg-canvas">
        <Header />
        <main className="mx-auto max-w-7xl px-6 py-8">
          <ShayChatSurface workspaceId={workspaceId} threadId={threadId} />
        </main>
      </div>
    </AuthGuard>
  );
}

