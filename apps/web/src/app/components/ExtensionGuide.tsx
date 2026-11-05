import { useContext, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertCircle, Check, Copy, Download } from 'lucide-react';
import ExtensionDemo, { type DemoMode } from './ExtensionDemo';
import SafariDemo, { type SafariDemoMode } from './SafariDemo';
import { UserContext } from '@/context/UserContext';
import { useExtensionStatus } from '../hooks/useExtensionStatus';

// Public `releases` bucket; publish a new build with `npm run release` in
// apps/extension. The path stays the same across versions.
const DOWNLOAD_URL =
    'https://xpovcmbrttmkhnrfspvo.supabase.co/storage/v1/object/public/releases/chrome/langfour-extension.zip';

const DEMOS: Record<DemoMode, { label: string; caption: string }> = {
    video: {
        label: 'Subtitles',
        caption: 'For watching. Unknown words light up in YouTube, Netflix and Prime Video subtitles; hover one to translate it.',
    },
    reader: {
        label: 'Reader',
        caption: 'For reading. Press ⌘⇧Y on any article to open it in a clean page where every unknown word is one click away.',
    },
    chatgpt: {
        label: 'ChatGPT',
        caption:
            'For chatting. Switch on Langfour in ChatGPT’s header and new words in its answers light up. Click one to translate it, or double-click it to add it to your learning words straight away.',
    },
};

const SAFARI_DEMOS: Record<SafariDemoMode, { label: string; caption: string }> = {
    video: {
        label: 'Subtitles',
        caption: 'For watching. Unknown words light up in YouTube’s captions; tap one to pause the video and translate it.',
    },
    reader: {
        label: 'Reader',
        caption: 'For reading. Tap Langfour in Safari’s page menu on any article to open it in a clean page where every unknown word is one tap away.',
    },
};

type Browser = 'chrome' | 'safari';

const isIOS = () =>
    /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

// ?browser= links straight to a tab. Otherwise iPhones land on the only one
// they can install. ProtectedRoute renders nothing on the server, so this only
// ever runs in the browser.
function initialBrowser(): Browser {
    const asked = new URLSearchParams(window.location.search).get('browser');
    if (asked === 'chrome' || asked === 'safari') return asked;
    return isIOS() ? 'safari' : 'chrome';
}

type Connection = { signedIn: boolean; wrongAccount: boolean; email: string | null; siteEmail?: string };

function StatusCard({ signedIn, wrongAccount, email, siteEmail, signInHint }: Connection & { signInHint: string }) {
    return (
        <div className="mt-5 max-w-md rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-900/5">
            <div className="flex items-start gap-3">
                <span
                    className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                        signedIn && !wrongAccount ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600'
                    }`}
                >
                    {signedIn && !wrongAccount ? <Check size={12} strokeWidth={3} /> : <AlertCircle size={12} strokeWidth={3} />}
                </span>
                <div className="text-sm">
                    <p className="font-medium text-gray-900">
                        {!signedIn
                            ? 'Installed, not signed in'
                            : wrongAccount
                              ? 'Signed in with a different account'
                              : 'Connected'}
                    </p>
                    <p className="mt-0.5 text-gray-500">
                        {!signedIn
                            ? signInHint
                            : wrongAccount
                              ? `The extension uses ${email}; this site uses ${siteEmail}. Words will go to the extension's account.`
                              : `Adding words to ${email ?? 'your account'}.`}
                    </p>
                </div>
            </div>
        </div>
    );
}

function CopyExtensionsUrl() {
    const [copied, setCopied] = useState(false);
    return (
        <button
            onClick={() => {
                navigator.clipboard.writeText('chrome://extensions');
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
            }}
            className="inline-flex items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-800 hover:bg-gray-200"
        >
            chrome://extensions
            {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} className="text-gray-400" />}
        </button>
    );
}

function ChromePanel({ connection, checking }: { connection: Connection | null; checking: boolean }) {
    const [downloaded, setDownloaded] = useState(false);

    const steps = [
        <>Unzip the downloaded <code className="rounded bg-gray-100 px-1 font-mono text-xs">langfour-extension.zip</code></>,
        <>Open <CopyExtensionsUrl /> in Chrome</>,
        <>Turn on <span className="font-medium text-gray-900">Developer mode</span> (top right)</>,
        <>Click <span className="font-medium text-gray-900">Load unpacked</span> and pick the folder, then sign in from the extension icon</>,
    ];

    return (
        <div role="tabpanel">
            <h1 className="text-2xl font-semibold text-gray-900">Langfour for Chrome</h1>
            <p className="mt-1.5 text-sm text-gray-500">Translate words and add them to your flashcards as you watch, read or chat with ChatGPT.</p>

            {connection ? (
                <StatusCard {...connection} signInHint="Click the Langfour icon in Chrome and sign in to start adding words." />
            ) : checking ? (
                <div className="mt-5 h-[42px]" />
            ) : downloaded ? (
                <motion.section
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, ease: 'easeOut' }}
                    className="mt-5 hidden max-w-xl rounded-xl bg-white p-5 shadow-sm ring-1 ring-indigo-600/20 md:block"
                >
                    <h2 className="text-base font-semibold text-gray-900">Finish installing</h2>
                    <p className="mt-0.5 text-sm text-gray-500">The download has started. Four steps in Chrome:</p>
                    <ol className="mt-4 space-y-3">
                        {steps.map((step, i) => (
                            <li key={i} className="flex items-center gap-3 text-sm text-gray-700">
                                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-indigo-600 text-xs font-medium text-white">
                                    {i + 1}
                                </span>
                                <span>{step}</span>
                            </li>
                        ))}
                    </ol>
                    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-gray-100 pt-4 text-sm">
                        <button
                            type="button"
                            onClick={() => window.location.reload()}
                            className="rounded-lg bg-indigo-600 px-3.5 py-2 font-medium text-white hover:bg-indigo-700"
                        >
                            I&apos;ve installed it, reload
                        </button>
                        <a href={DOWNLOAD_URL} download="langfour-extension.zip" className="text-gray-500 hover:text-gray-800">
                            Download again
                        </a>
                    </div>
                </motion.section>
            ) : (
                <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
                    <a
                        href={DOWNLOAD_URL}
                        download="langfour-extension.zip"
                        onClick={() => setDownloaded(true)}
                        className="hidden md:inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
                    >
                        <Download size={16} />
                        Download extension
                    </a>
                    <span className="hidden md:inline text-xs text-gray-400">Free · Chrome on desktop</span>
                    <p className="md:hidden text-sm text-gray-600">Open this page on a computer with Chrome to install.</p>
                </div>
            )}

            {(Object.keys(DEMOS) as DemoMode[]).map((key) => (
                <section key={key} className="mt-10">
                    <h2 className="text-base font-semibold text-gray-900">{DEMOS[key].label}</h2>
                    <p className="mt-1 mb-4 max-w-xl text-sm text-gray-500">{DEMOS[key].caption}</p>
                    <ExtensionDemo mode={key} />
                </section>
            ))}
        </div>
    );
}

function SafariPanel({ connection }: { connection: Connection | null }) {
    return (
        <div role="tabpanel">
            <h1 className="text-2xl font-semibold text-gray-900">Langfour for Safari</h1>
            <p className="mt-1.5 text-sm text-gray-500">Translate words and add them to your flashcards as you read and watch on your iPhone.</p>

            {connection ? (
                <StatusCard {...connection} signInHint="Open the reader from Safari’s page menu and sign in under Aa to start adding words." />
            ) : (
                <p className="mt-5 text-xs text-gray-400">Free · Safari on iPhone · Not on the App Store yet</p>
            )}

            {(Object.keys(SAFARI_DEMOS) as SafariDemoMode[]).map((key) => (
                <section key={key} className="mt-10">
                    <h2 className="text-base font-semibold text-gray-900">{SAFARI_DEMOS[key].label}</h2>
                    <p className="mt-1 mb-4 max-w-xl text-sm text-gray-500">{SAFARI_DEMOS[key].caption}</p>
                    <SafariDemo mode={key} />
                </section>
            ))}
        </div>
    );
}

export default function ExtensionGuide() {
    const [browser, setBrowser] = useState<Browser>(initialBrowser);
    const [ios] = useState(isIOS);
    const ext = useExtensionStatus();
    const { user } = useContext(UserContext);
    const connection: Connection | null =
        ext.state === 'installed'
            ? {
                  signedIn: ext.signedIn,
                  wrongAccount: ext.signedIn && !!ext.email && !!user?.email && ext.email.toLowerCase() !== user.email.toLowerCase(),
                  email: ext.email,
                  siteEmail: user?.email ?? undefined,
              }
            : null;

    const switchBrowser = (next: Browser) => {
        setBrowser(next);
        const url = new URL(window.location.href);
        url.searchParams.set('browser', next);
        window.history.replaceState(null, '', url);
    };

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="max-w-3xl px-4 md:pl-10 md:pr-3 py-8 pb-16">
                <div role="tablist" aria-label="Browser" className="mb-6 flex gap-6 border-b border-gray-200">
                    {(['chrome', 'safari'] as const).map((key) => (
                        <button
                            key={key}
                            type="button"
                            role="tab"
                            aria-selected={browser === key}
                            onClick={() => switchBrowser(key)}
                            className={`-mb-px border-b-2 px-1 pb-3 text-sm font-medium ${
                                browser === key ? 'border-indigo-600 text-gray-900' : 'border-transparent text-gray-500 hover:text-gray-800'
                            }`}
                        >
                            {key === 'chrome' ? 'Chrome' : 'Safari'}
                        </button>
                    ))}
                </div>

                {/* The bridge only says that some extension answered, so each tab
                    trusts it only on the devices that browser's extension runs on. */}
                {browser === 'chrome' ? (
                    <ChromePanel connection={ios ? null : connection} checking={ext.state === 'checking'} />
                ) : (
                    <SafariPanel connection={ios ? connection : null} />
                )}
            </div>
        </div>
    );
}
