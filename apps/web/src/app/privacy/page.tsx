export const metadata = { title: 'Privacy Policy – Langfour' };

// TODO(owner): add a contact address, and add your retention and deletion terms
// to "Your data". Left out on purpose: they are commitments, not facts about the code.
const CONTACT_EMAIL: string | null = null;

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section className="mt-8">
        <h2 className="text-base font-semibold text-gray-900">{title}</h2>
        <div className="mt-2 space-y-3">{children}</div>
    </section>
);

export default function PrivacyPage() {
    return (
        <main className="mx-auto max-w-2xl px-4 py-12 text-sm leading-relaxed text-gray-600">
            <h1 className="text-2xl font-semibold text-gray-900">Privacy Policy</h1>
            <p className="mt-1 text-gray-500">Langfour website and Chrome extension. Last updated 6 October 2026.</p>

            <Section title="Introduction">
                <p>
                    This policy explains what information Langfour collects when you use the website at app.langfour.com and the
                    Langfour Chrome extension, and how that information is used.
                </p>
            </Section>

            <Section title="Information we collect">
                <p>
                    <strong className="text-gray-900">Account information.</strong> When you sign in we collect your email address.
                    Sign-in uses a one-time link sent to that address.
                </p>
                <p>
                    <strong className="text-gray-900">Learning data.</strong> We store the words you add to your flashcards, the
                    list of words you know, and the language you are learning.
                </p>
                <p>
                    <strong className="text-gray-900">Text you look up.</strong> When you hover a word or select a passage in the
                    extension, that word or passage is sent to our server to be translated. The rest of the page is not sent.
                </p>
                <p>
                    <strong className="text-gray-900">YouTube channels.</strong> If you use the bookmark button on a YouTube
                    channel, the ID of that channel is sent to our server.
                </p>
            </Section>

            <Section title="What the extension reads on your pages">
                <p>
                    On YouTube, Netflix and Prime Video the extension reads the subtitle text shown on screen so that it can
                    highlight words you have not learned yet. In reader mode it reads the article on the page you opened it on,
                    and only when you start reader mode. The extension does not collect your browsing history.
                </p>
            </Section>

            <Section title="How we use information">
                <p>
                    We use this information to provide Langfour: to sign you in, to translate the words and passages you look up,
                    and to keep your flashcards and progress.
                </p>
            </Section>

            <Section title="Services that process information">
                <p>
                    Account and learning data are stored with Supabase. Translations are produced by language models accessed
                    through OpenRouter, which receives the word or passage you look up. Our server and website are hosted on Koyeb
                    and Vercel.
                </p>
            </Section>

            <Section title="Data stored in your browser">
                <p>
                    The extension keeps your sign-in session, your selected language and your list of known words in your browser.
                    Signing out from the extension&apos;s toolbar popup removes the stored session.
                </p>
            </Section>

            <Section title="Changes to this policy">
                <p>If this policy changes, the updated version will be posted on this page with a new date.</p>
            </Section>

            {CONTACT_EMAIL && (
                <Section title="Contact">
                    <p>
                        For questions about this policy, contact <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
                    </p>
                </Section>
            )}
        </main>
    );
}
