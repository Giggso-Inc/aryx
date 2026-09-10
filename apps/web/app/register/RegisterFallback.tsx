export function RegisterPageFallback() {
  return (
    <div className="min-h-screen bg-canvas px-6 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-2xl items-center justify-center">
        <div className="w-full rounded-[2rem] border border-navy-100 bg-white/96 p-8 shadow-[0_24px_70px_rgba(15,31,61,0.12)] backdrop-blur">
          <p className="text-sm text-subtle">Loading registration...</p>
        </div>
      </div>
    </div>
  );
}
