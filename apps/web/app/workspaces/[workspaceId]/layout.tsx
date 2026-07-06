import { AuthGuard } from "@/components/shay/AuthGuard";
import { WorkspaceRouteBridge } from "@/components/shay/WorkspaceRouteBridge";

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  return (
    <AuthGuard>
      <WorkspaceRouteBridge shayWorkspaceId={workspaceId}>
        {children}
      </WorkspaceRouteBridge>
    </AuthGuard>
  );
}
