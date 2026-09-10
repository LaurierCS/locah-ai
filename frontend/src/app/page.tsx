export default function Home() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">LOCAH.ai</h1>
      <p className="mt-3 text-neutral-600">
        Ask a question about Laurier and get an answer with a link to the page it came from.
      </p>
      <p className="mt-8 rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-600">
        Chat interface is under construction — see{" "}
        <span className="font-mono">docs/SDD.md §5.6</span>. Sprint S2 delivers the first
        end-to-end cited answer.
      </p>
    </main>
  );
}
