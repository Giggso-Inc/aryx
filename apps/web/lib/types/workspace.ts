export interface Workspace {
  id: number;
  name: string;
  description?: string;
  context?: string;
  brief?: Record<string, unknown>;
}
