import { Suspense } from "react";
import { WorkspaceSettingsPage } from "@/components/shay/WorkspaceSettingsPage";

export default async function Page({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <Suspense fallback={<div className="p-6 text-sm text-subtle">Loading workspace settings...</div>}>
      <WorkspaceSettingsPage workspaceId={workspaceId} />
    </Suspense>
  );
}
