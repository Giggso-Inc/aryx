import BriefPage from "@/app/brief/page";
import { AuthGuard } from "@/components/shay/AuthGuard";
import { WorkspaceRouteBridge } from "@/components/shay/WorkspaceRouteBridge";

export default async function Page({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  return (
    <AuthGuard>
      <WorkspaceRouteBridge shayWorkspaceId={workspaceId}>
        <BriefPage />
      </WorkspaceRouteBridge>
    </AuthGuard>
  );
}
