/**
 * The public statement of what LOCAH is and is not.
 * Required by BR-8 and non-negotiable — do not remove or soften without club exec sign-off.
 */
export default function About() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">About LOCAH.ai</h1>

      <p className="mt-4 text-neutral-700">
        LOCAH.ai is a student-built assistant over Wilfrid Laurier University&apos;s publicly
        published web pages. It is run by the Laurier Computing Society. It is not an official
        university service, and it is not a substitute for speaking to an advisor.
      </p>

      <h2 className="mt-10 text-xl font-semibold">What it does</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-neutral-700">
        <li>Answers questions from Laurier&apos;s public pages, citing the page each answer came from.</li>
        <li>Shows you both sources when two official Laurier pages disagree, instead of picking one.</li>
        <li>Tells you it does not know, and who to ask, rather than guessing.</li>
        <li>Points you to support services Laurier already publishes.</li>
      </ul>

      <h2 className="mt-10 text-xl font-semibold">What it does not do</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-neutral-700">
        <li>It does not store your personal information. There are no accounts.</li>
        <li>It does not screen, diagnose, or counsel, and it gives no wellbeing advice of its own.</li>
        <li>It does not read your student record.</li>
        <li>It does not send anything to anyone on your behalf.</li>
      </ul>

      <h2 className="mt-10 text-xl font-semibold">If you need to talk to someone</h2>
      <p className="mt-3 text-neutral-700">
        LOCAH is not a support service. If you are in distress, please contact a person directly.
        {/* TODO(frontend-pod): link Laurier Student Wellness Centre, Good2Talk, and campus
            emergency numbers here before the pilot opens. Verify every number against the
            published Laurier page — these must never be wrong. */}
      </p>
    </main>
  );
}
