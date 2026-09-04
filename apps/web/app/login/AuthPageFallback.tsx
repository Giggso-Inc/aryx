import { Header } from "@/components/brand/Header";

export function AuthPageFallback({ message }: { message: string }) {
  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-6xl items-center justify-center px-6 py-12">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <p className="text-sm text-subtle">{message}</p>
        </div>
      </main>
    </div>
  );
}
